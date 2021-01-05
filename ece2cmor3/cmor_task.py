from builtins import object
import logging
from ece2cmor3 import cmor_source, cmor_target

# Logger instance
log = logging.getLogger(__name__)

conversion_key = "convert"
filter_output_key = "filter_path"
output_path_key = "path"
output_frequency_key = "output_freq"

status_initialized = 0
status_postprocessing = 1
status_postprocessed = 2
status_cmorizing = 3
status_cmorized = 4
status_finished = 5
status_failed = -1


# Cmorization task class, containing source and targets.
class cmor_task(object):

    def __init__(self, source_, target_):
        if not isinstance(source_, cmor_source.cmor_source):
            raise Exception("Invalid source argument type for cmor task:", type(source_))
        if not isinstance(target_, cmor_target.cmor_target):
            raise Exception("Invalid target argument type for cmor task:", type(target_))
        self.source = source_
        self.target = target_
        self.status = status_initialized

    def next_state(self):
        if self.status == status_failed:
            log.error("Attempt to increase failed status for task %s in %s ignored" % (self.target.variable,
                                                                                       self.target.table))
        elif self.status == status_finished:
            log.warning("Attempt to increase finished status for task %s in %s ignored" % (self.target.variable,
                                                                                           self.target.table))
        else:
            self.status += 1
        return self.status

    def set_failed(self):
        self.status = status_failed
        return self.status
