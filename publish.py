"""
This module is a collection of classes and methods to perform the actual posting of content to
 Mastodon / Twitter
"""

import arrow
from mastodon import MastodonError


class MastodonPublisher:
    """
    Ease the publishing of content to Mastodon
    """

    def __init__(self, mastodon, userinfo, logger):
        self.mastodon = mastodon
        self.userinfo = userinfo
        self.logger = logger

    def delete_toots(self, older_than_days):
        """
        Deletes old toots that are older than "older_than_days" days old in batches of up to
        whatever the limit is set to in the account_statuses call to mastodon. This limit should be
        kept low enough to not trigger rate limiting by the mastodon server.
        For example with the limit set to 10, this method will delete up to 10 old toots and then
        return.

        Arguments:
            older_than_days (int): This value is used to determine the most recent toot that will
                                    be considered for deletion.
        """
        try:
            toots = self.mastodon.account_statuses(self.userinfo['id'], limit=10)
            now = arrow.get(arrow.now().format('YYYY-MM-DD HH:mm:ss'), 'YYYY-MM-DD HH:mm:ss')
            oldest_to_keep = now.shift(days=-older_than_days)

            # List of toots is paginated. This while loop finds the first "page" of toots that
            # contains toots old enough to need deleting
            while True:
                if len(toots) == 0:
                    break
                last_toot_created_at = arrow.get(toots[-1]['created_at'])
                if last_toot_created_at < oldest_to_keep:
                    break
                max_id = toots[-1]['id']
                self.logger.debug('Last toot in list %s from %s is not older than %s',
                                  max_id, last_toot_created_at, oldest_to_keep)
                toots = self.mastodon.account_statuses(self.userinfo['id'], max_id=max_id, limit=10)

            # Actually deleting toots that are older than "older_than_days"
            for toot in toots:
                created_at = arrow.get(toot['created_at'])
                if created_at < oldest_to_keep:
                    self.logger.info('Deleting toot %s from %s', toot['url'], toot['created_at'])
                    self.mastodon.status_delete(toot['id'])
        except MastodonError as mastodon_error:
            self.logger.error('Encountered error while deleting_toots: %s ', mastodon_error)
