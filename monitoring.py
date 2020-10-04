"""
Classes / Methods to assist with monitoring continued operation of tootboot.
"""
import requests


class HealthChecks:
    """
    Class to make monitoring the operation of tootboot with Healthchecks (healthchecks.io) easier.
    """

    def __init__(self, base_url, uid, logger=None):
        self.base_url = base_url
        self.uid = uid
        self.logger = logger

    def check(self, data=None, check_type=None):
        """
        Check in with a Healthchecks installation

        Keyword Arguments:
            data (string):
                Data to send along with the check in. Can e used to include a short status along
                with the check in.
            check_type (string):
                - Type of check in. An empty (None) check_type signals an ok check in and also the
                    successful completion of an earlier 'start' check in type.
                - check_type of 'start' signals the start of a process
                - check_type of 'fail' signals the failure. This can include the failure of an
                    earlier start check in
        """
        url = self.base_url + self.uid
        if check_type is not None:
            url = url + '/' + check_type
        try:
            response = requests.put(url, data=data, timeout=3)
            response.raise_for_status()
            if self.logger is not None:
                check_type = 'OK' if check_type is None else check_type
            self.logger.info('Monitoring ping sent of type: %s' % check_type)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as requests_exception:
            if self.logger is not None:
                self.logger.error('During Monitoring "OK Ping" we got: %s' % requests_exception)

    def check_ok(self, data=None):
        """
        Convenience method to signal an OK completion of a process.
        """
        self.check(data=data)

    def check_start(self, data=None):
        """
        Convenience method to signal the start of a process
        """
        self.check(data=data, check_type='start')

    def check_fail(self, data=None):
        """
        Convenience method to signal the failure of a process
        """
        self.check(data=data, check_type='fail')
