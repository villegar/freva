from django.db import models
from django.contrib.auth.models import User
from evaluation_system.model.plugins.models import Version, Parameter
from evaluation_system.misc.utils import PrintableList
import re
import os
import json


class History(models.Model):
    """
    The class belongs to a table containing all processes, which were started with analyze.
    """

    class Meta:
        """
        Set the user's permissions
        """

        permissions = (
            ("history_submit_job", "Can submit a job"),
            ("history_cancel_job", "Can cancel a job"),
            ("browse_full_data", "Can search all data"),
        )
        app_label = "history"

    class processStatus:
        """
        The allowed statuses
        finished           - the process finished and produced output files
        finished_no_output - the process finished, but no output files were created
        scheduled          - the job was send to slurm
        running            - the job is executed
        broken             - an exception occurred
        not_scheduled      - an error occurred during scheduling
        """

        finished, finished_no_output, broken, running, scheduled, not_scheduled = list(
            range(6)
        )

    class Flag:
        """
        The possible flags are:
        free    - can be accessed by all
        guest   - like public and permission for guest users
        public  - the data is accessible for every registered user
        shared  - the data is can be only accessed by certain users (to be implemented)
        private - the data is private
        deleted - the data set will be hidden
        """

        public, shared, private, deleted = range(4)
        guest = 8
        free = 9

    STATUS_CHOICES = (
        (processStatus.finished, "finished"),
        (processStatus.finished_no_output, "finished (no output)"),
        (processStatus.broken, "broken"),
        (processStatus.running, "running"),
        (processStatus.scheduled, "scheduled"),
        (processStatus.not_scheduled, "not scheduled"),
    )

    FLAG_CHOICES = (
        (Flag.public, "public"),
        (Flag.shared, "shared"),
        (Flag.private, "private"),
        (Flag.deleted, "deleted"),
        (Flag.guest, "users and guest"),
        (Flag.free, "no login required"),
    )

    #: Date and time when the process were scheduled
    timestamp = models.DateTimeField()
    #: Name of the tool
    tool = models.CharField(max_length=50)
    #: Version of the tool
    version = models.CharField(max_length=20)
    #: User ID
    version_details = models.ForeignKey(Version, on_delete=models.CASCADE, default=1)
    #: The configuration this can be quiet lengthy
    configuration = models.TextField()
    #: Output file generated by SLURM
    slurm_output = models.TextField()
    #: User ID
    uid = models.ForeignKey(
        User, on_delete=models.CASCADE, to_field="username", db_column="uid"
    )
    #: Status (scheduled, running, finished, cancelled)
    status = models.IntegerField(choices=STATUS_CHOICES)
    #: Flag (deleted, private, shared, public)
    flag = models.IntegerField(choices=FLAG_CHOICES, default=Flag.public)
    # User defined caption for the analysis
    caption = models.CharField(max_length=255, blank=True, null=True)

    def __init__(self, *args, **kwargs):
        """
        Creates a dictionary for projectStatus
        """
        self.status_dict = dict()
        public_props = (
            name for name in dir(self.processStatus) if not name.startswith("_")
        )
        for name in public_props:
            self.status_dict[getattr(self.processStatus, name)] = name

        super(History, self).__init__(*args, **kwargs)

    def __str__(self, compact=True):  # pragma: no cover
        conf_str = ""

        if compact:
            conf_str = str(self.configuration)
            if len(conf_str) > 70:
                conf_str = conf_str[:67] + "..."
            version = ""
        else:
            items = ["%15s=%s" % (k, v) for k, v in sorted(self.config_dict().items())]
            if items:
                # conf_str = '\n' + json.dumps(self.configuration, sort_keys=True, indent=2)
                conf_str = "\nConfiguration:\n%s" % "\n".join(items)
            # if self.results:
            #     conf_str = '%s\nOutput:\n%s' % (conf_str, '\n'.join(out_files))

            version = "%s %s" % (
                self.version,
                self.version_details.internal_version_tool,
            )

        return "%s) %s%s [%s] %s %s" % (
            self.pk,
            self.tool,
            version,
            self.timestamp,
            self.status_name(),
            conf_str,
        )

    def slurmId(self):
        id = re.sub(r".*\-", "", self.slurm_output)
        id = re.sub(r"\..*", "", id)

        # always return a number, even when the string is too short
        # (the default value for the string is '0')
        if not id:
            id = "0"

        return id

    def config_dict(self, load_default_values=False):
        """
        Converts the configuration to a dictionary
        """

        d = {}

        config = Configuration.objects.filter(history_id_id=self.id).order_by("pk")

        for c in config:
            name = c.parameter_id.parameter_name
            if load_default_values and c.is_default:
                d[name] = json.loads(c.parameter_id.default)
            else:
                d[name] = json.loads(c.value)

            # we have to take care that some special values are casted to the right class
            if c.parameter_id.parameter_type == "Range" and d[name] is not None:
                d[name] = PrintableList(d[name])

        return d

    def status_name(self):
        """
        Returns status as string
        """
        return self.status_dict[self.status]

    def get_slurm_status(self):
        """
        Method to get the slurm status.
        """
        slurm_id = self.slurmId()
        # not started with slurm
        if slurm_id == "0":
            return False
        try:
            cmd = "sacct -X -p -j %s" % slurm_id
            p = os.popen(cmd, "r")
            header = p.readline().split("|")
            entry = p.readline().split("|")
            index = header.index("State")
            return entry[index]
        # If "sacct" is not configured, we have to use "squeue"
        except ValueError:
            cmd = "squeue -h"
            p = os.popen(cmd, "r")
            while True:
                line = p.readline()
                if not line:
                    if self.status == 3:  # self.STATUS_CHOICES.running:
                        return "Cancelled"
                    return self.status_name()
                if slurm_id in line:
                    if " PD " in line:
                        return "Scheduled"
                    return "Running"

    @staticmethod
    def find_similar_entries(
        config, uid=None, max_impact=Parameter.Impact.affects_plots, max_entries=-1
    ):
        """
        Find entries which are similar to a given configuration.
        :param config: The configuration as array.
        :type config: array of history_configuration objects
        :param uid: the users id to find private results
        :type uid: str
        :param max_impact: The maximal impact level recognized
        :type max_impact: integer
        :param max_entries: The maximal number of results to be returned
        :type max_entries: integer
        """

        from django.db.models import Count, Q

        o = Configuration.objects.all()

        length = 0

        parameter = None

        # We use django Q to create the query.
        # this routine builds the parameter to query.
        for c in config:
            if c.parameter_id.impact <= max_impact:
                # both parameter and value have to match
                andparam = Q(parameter_id_id=c.parameter_id) & Q(value=c.value)

                # concatenate all parameter pairs with an or condition
                if parameter is None:
                    parameter = andparam
                else:
                    parameter = parameter | andparam

                length += 1

        if parameter is not None:
            o = o.filter(parameter)
            o = o.values("history_id_id").annotate(hcount=Count("history_id"))

            # using a less than equal relation would allow to access matches
            # which are equal to n percent.
            o = o.filter(hcount=length).order_by("-history_id_id")
        else:
            o = []

        # there should be an easier method to get a list the ids of the found
        # datasets
        history_list = []

        valid_status = [
            History.processStatus.finished,
            History.processStatus.finished_no_output,
        ]

        public_flags = [History.Flag.free, History.Flag.public]

        private_flags = [
            History.Flag.private,
            History.Flag.deleted,
            History.Flag.shared,
        ]

        for row in o:
            h = History.objects.filter(pk=row["history_id_id"])[0]

            if h.status in valid_status and (
                h.flag in public_flags or (h.uid_id == uid and h.flag in private_flags)
            ):
                # append entry to list and stop if the desired list length is reached
                history_list.append(h)

                if len(history_list) == max_entries:
                    break

        return history_list


class Result(models.Model):
    """
    This class belongs to a table storing results.
    The output files of process will be recorded here.
    """

    class Filetype:
        """
        Different IDs of file types
        data      - ascii or binary data to download
        plot      - a file which can be converted to a picture
        preview   - a local preview picture (copied or converted)
        """

        data, plot, preview = range(3)
        unknown = 9

    FILE_TYPE_CHOICES = (
        (Filetype.data, "data"),
        (Filetype.plot, "plot"),
        (Filetype.preview, "preview"),
        (Filetype.unknown, "unknown"),
    )

    #: history id
    history_id = models.ForeignKey(History, on_delete=models.CASCADE)
    #: path to the output file
    output_file = models.TextField()
    #: path to preview file
    preview_file = models.TextField(default="")
    #: specification of a file type
    file_type = models.IntegerField(choices=FILE_TYPE_CHOICES)

    class Meta:
        """
        Set the user's permissions
        """

        permissions = (("results_view_others", "Can view results from other users"),)
        app_label = "history"

    def fileExtension(self):
        """
        Returns the file extension of the result file
        """
        from os import path

        return path.splitext(self.output_file)[1]

    # some not yet implemented ideas
    #: Allows a logical clustering of results
    # group           = models.IntegerField(max_length=2)
    #: Defines an order for each group
    # group_order     = models.IntegerField(max_length=2)


class ResultTag(models.Model):
    """
    This class belongs to a table storing results.
    The output files of process will be recorded here.
    """

    class flagType:
        caption = 0

    class Meta:
        app_label = "history"

    TYPE_CHOICES = ((flagType.caption, "Caption"),)

    #: result id
    result_id = models.ForeignKey(Result, on_delete=models.CASCADE)
    #: specification of a file type
    type = models.IntegerField(choices=TYPE_CHOICES)
    #: path to the output file
    text = models.TextField()


class HistoryTag(models.Model):
    """
    This class belongs to a table storing results.
    The output files of process will be recorded here.
    """

    class tagType:
        [caption, note_public, note_private, note_deleted, follow, unfollow] = list(
            range(6)
        )

    class Meta:
        app_label = "history"

    TYPE_CHOICES = (
        (tagType.caption, "Caption"),
        (tagType.note_public, "Public note"),
        (tagType.note_private, "Private note"),
        (tagType.note_deleted, "Deleted note"),
        (tagType.follow, "Follow"),
        (tagType.unfollow, "Unfollow"),
    )

    #: result id
    history_id = models.ForeignKey(History, on_delete=models.CASCADE)
    #: specification of a file type
    type = models.IntegerField(choices=TYPE_CHOICES)
    #: path to the output file
    text = models.TextField()
    #: the user, who tagged the history entry
    uid = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        to_field="username",
        db_column="uid",
        null=True,
        default=None,
    )


class Configuration(models.Model):
    """
    Holds the configuration
    """

    #: history id
    history_id = models.ForeignKey(
        History, on_delete=models.CASCADE, related_name="history_id"
    )

    #: parameter number
    parameter_id = models.ForeignKey(
        Parameter, on_delete=models.CASCADE, related_name="parameter_id"
    )

    #: md5 checksum of value (not used, yet)
    md5 = models.CharField(max_length=32, default="")

    #: value
    value = models.TextField(null=True, blank=True)

    # is the default value used?
    is_default = models.BooleanField()

    class Meta:
        app_label = "history"
