"""
This module contains helper classes and methods to assist with determining if a reddit post should
be published on Mastodon / Twitter
"""
import csv
import os
import time


class PostRecorder:
    """
    Implements logging of reddit posts published to Mastodon and twitter and also checking against
    the log of published content to determine if a post would be a duplicate.
    """

    def __init__(self, cache_file, logger):
        self.cache_file = cache_file
        self.logger = logger

        # Make sure logging file and media directory exists
        if not os.path.exists(self.cache_file):
            with open(self.cache_file, 'w', newline='') as new_cache_file:
                default = ['Reddit post ID', 'Date and time', 'Post link', 'Media Checksum']
                csv_writer = csv.writer(new_cache_file)
                csv_writer.writerow(default)
            logger.info('%s file not found, created a new one', self.cache_file)
            new_cache_file.close()

    def duplicate_check(self, identifier):
        """
        Checks if "identifier can be found in log file of content posted to Mastodon / Twitter

        Arguments:
            identifier (string):
                Any identifier we want to make sure has not already been posted. This can be id of
                reddit post, url of media attachment file to be posted, or checksum of media
                 attachment file.

        Returns:
            boolean:
                False if "identifier" is not in log of content already posted to Mastodon / Twitter
                True if "identifier" has been found in log of content.
        """
        value = False
        with open(self.cache_file, 'rt', newline='') as cache_file:
            reader = csv.reader(cache_file, delimiter=',')
            for row in reader:
                if identifier in row:
                    value = True
        cache_file.close()
        return value

    def log_post(self, reddit_id, post_url, shared_url, check_sum):
        """
        Logs details about reddit posts that have been published.

        Arguments:
            reddit_id (string):
                Id of post on reddit that was published to Mastodon / Twitter
            post_url (string):
                URL on Mastodon / Twitter of content that was posted
            shared_url (string):
                URL of media attachment that was shared on Mastodon / Twitter
            check_sum (string):
                Checksum of media attachment that was shared on Mastodon / Twitter. This enables
                 checking for duplicate media even if file has been renamed.
        """
        with open(self.cache_file, 'a', newline='') as cache_file:
            date = time.strftime("%d/%m/%Y") + ' ' + time.strftime("%H:%M:%S")
            cache_csv_writer = csv.writer(cache_file, delimiter=',')
            cache_csv_writer.writerow([reddit_id, date, post_url, shared_url, check_sum])
        cache_file.close()
