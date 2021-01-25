"""
This module contains helper classes and methods to assist with determining if a reddit post should
be published on Mastodon / Twitter
"""
import configparser
import csv
import logging
import os
import sys
import time
from dataclasses import dataclass
from distutils.util import strtobool
from typing import List

import coloredlogs


class PostRecorder:
    """
    Implements logging of reddit posts published to Mastodon and twitter and also checking against
    the log of published content to determine if a post would be a duplicate.
    """

    def __init__(self, cache_file: str, logger: logging.Logger):
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

    def duplicate_check(self, identifier: str) -> bool:
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

    def log_post(self, reddit_id: str, post_url: str, shared_url: str, check_sum: str):
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


@dataclass
class BotConfig:
    """
    Dataclass holding configuration values for general behaviour of tootbot
    """
    cache_file: str
    post_recorder: PostRecorder
    delay_between_posts: int
    run_once_only: bool
    hash_tags: List
    log_level: str
    logger: logging.Logger


@dataclass
class RedditReaderConfig:
    """
    Dataclass holding configuration values related to Reddit
    """
    post_limit: int
    nsfw_allowed: bool
    nsfw_marked: bool
    spoilers: bool
    self_posts: bool
    stickied_allowed: bool


@dataclass
class PromoConfig:
    """
    Dataclass holding configuration values related to Promotional message settings
    """
    every: int
    message: str


@dataclass
class HealthCheckConfig:
    """
    Dataclass holding configuration values around Healthchecks monnitorint
    """
    enabled: bool
    base_url: str
    uuid: str


@dataclass
class MediaConfig:
    """
    Dataclass holding configuration values around attached media
    """
    folder: str
    media_only: bool


@dataclass
class MastodonConfig:
    """
    Dataclass holding configuration values for Mastodon settings.
    This also stores the number of times the mastodon API has returned an error to allow throttling
    of posting toots in a controlled manner
    """
    domain: str
    media_always_sensitive: bool
    delete_after: int
    throttling_enabled: bool
    throttling_max_delay: int
    number_of_errors: int


@dataclass
class SubredditConfig:
    """
    Dataclass to hold configuration settings about the subreddits to be monitored
    """
    name: str
    tags: str


@dataclass
class Configuration:
    """
    Dataclass to hold all settings for tootbot.
    """
    bot: BotConfig
    subreddits: List[SubredditConfig]
    promo: PromoConfig
    health: HealthCheckConfig
    media: MediaConfig
    mastodon_config: MastodonConfig
    reddit: RedditReaderConfig

    def __init__(self) -> None:

        # Make sure config file exists
        try:
            config = configparser.ConfigParser()
            config.read('config.ini')
        except configparser.Error as config_error:
            print('[ERROR] Error while reading config file: %s', config_error)
            sys.exit(1)

        # Set-up logging
        log_level = 'INFO'
        if config['BotSettings']['LogLevel']:
            log_level = config['BotSettings']['LogLevel']
        logger = logging.getLogger(__name__)
        coloredlogs.install(level=log_level,
                            fmt='%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s',
                            datefmt='%H:%M:%S')

        # Bot settings
        bot_settings = config['BotSettings']
        hash_tags = ''
        if config['BotSettings']['Hashtags']:
            # Parse list of hashtags
            hash_tags_string = config['BotSettings']['Hashtags']
            hash_tags = [x.strip() for x in hash_tags_string.split(',')]
        self.bot = BotConfig(cache_file=bot_settings['CacheFile'],
                             post_recorder=PostRecorder(bot_settings['CacheFile'], logger),
                             delay_between_posts=int(bot_settings['DelayBetweenPosts']),
                             run_once_only=strtobool(bot_settings['RunOnceOnly']),
                             hash_tags=hash_tags,
                             log_level=bot_settings['LogLevel'],
                             logger=logger)

        # Settings related to reddit reader
        self.reddit = RedditReaderConfig(
            post_limit=int(bot_settings['PostLimit']),
            nsfw_allowed=strtobool(bot_settings['NSFWPostsAllowed']),
            nsfw_marked=strtobool(bot_settings['NSFWPostsMarked']),
            spoilers=strtobool(bot_settings['SpoilersAllowed']),
            self_posts=strtobool(bot_settings['SelfPostsAllowed']),
            stickied_allowed=strtobool(bot_settings['StickiedPostsAllowed']),
        )

        # Settings related to promotional messages
        promo_settings = config['PromoSettings']
        self.promo = PromoConfig(every=int(promo_settings['PromoEvery']),
                                 message=promo_settings['PromoMessage'])

        # HealthChecks related settings
        healthchecks_settings = config['HealthChecks']
        health_enabled = False
        logger.debug('Healthcheck settings: %s', healthchecks_settings)
        logger.debug('Base_url ->%s<-', healthchecks_settings['BaseUrl'])
        logger.debug('Len base url: %s', len(healthchecks_settings['BaseUrl']))
        if len(healthchecks_settings['BaseUrl']) > -1:
            health_enabled = True
        self.health = HealthCheckConfig(enabled=health_enabled,
                                        base_url=healthchecks_settings['BaseUrl'],
                                        uuid=healthchecks_settings['UUID'])

        # Settings related to media attachments
        media_settings = config['MediaSettings']
        self.media = MediaConfig(folder=media_settings['MediaFolder'],
                                 media_only=strtobool(media_settings['MediaPostsOnly']))

        # Mastodon info
        mastodon_settings = config['Mastodon']
        self.mastodon_config = MastodonConfig(domain=mastodon_settings['InstanceDomain'],
                                              media_always_sensitive=strtobool(
                                                  mastodon_settings['SensitiveMedia']),
                                              delete_after=int(
                                                  mastodon_settings['DeleteAfterDays']),
                                              throttling_enabled=strtobool(
                                                  mastodon_settings['ThrottlingEnabled']),
                                              throttling_max_delay=int(
                                                  mastodon_settings['ThrottlingMaxDelay']),
                                              number_of_errors=0)

        self.subreddits = []
        for subreddit, hashtags in config.items('Subreddits'):
            self.subreddits.append(SubredditConfig(subreddit, hashtags))

        logger.debug("After loading of config: %s", self)
