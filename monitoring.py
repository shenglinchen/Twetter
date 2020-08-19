import requests


class HealthChecks:

    def __init__(self, base_url, uid, logger=None):
        self.base_url = base_url
        self.uid = uid
        self.logger = logger

    def check(self, data=None, check_type=None):
        url = self.base_url + self.uid
        if check_type is not None:
            url = url + '/' + check_type
        try:
            response = requests.put(url, data=data, timeout=3)
            response.raise_for_status()
            if self.logger is not None:
                check_type = 'OK' if check_type is None else check_type
            self.logger.info('Monitoring ping sent of type: %s' % check_type)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError) as ce:
            if self.logger is not None:
                self.logger.error('During Monitoring "OK Ping" we got: %s' % ce)

    def check_ok(self, data=None):
        self.check(data=data)

    def check_start(self, data=None):
        self.check(data=data, check_type='start')

    def check_fail(self, data=None):
        self.check(data=data, check_type='fail')
