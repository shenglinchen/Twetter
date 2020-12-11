"""
This module contains the main logic for tootbot.
"""
import os
import sys
import time

import requests

from collect import LinkedMediaHelper
from collect import RedditHelper
from control import Configuration
from monitoring import HealthChecks
from publish import MastodonPublisher

CODE_VERSION_MAJOR = 3  # Current major version of this code
CODE_VERSION_MINOR = 0  # Current minor version of this code
CODE_VERSION_PATCH = 1  # Current patch version of this code

config = Configuration()

# Check for updates
try:
    response = requests.get(
        'https://gitlab.com/marvin8/tootbot/-/raw/main/update-check/release-version.txt')
    response.raise_for_status()
    repo_version = response.content.decode('utf-8').strip().partition('.')
    repo_version_major = int(repo_version[0].strip())
    repo_minor_version_to_check = repo_version[2].strip().partition('.')
    if repo_minor_version_to_check[1] == '':
        repo_version_minor = int(repo_minor_version_to_check[0].strip())
        repo_version_patch = 0
    else:
        repo_version_minor = int(repo_minor_version_to_check[0].strip())
        repo_version_patch = int(repo_minor_version_to_check[2].strip())

    code_version_numeric = CODE_VERSION_MAJOR * 1000000
    code_version_numeric += CODE_VERSION_MINOR * 1000
    code_version_numeric += CODE_VERSION_PATCH
    repo_version_numeric = repo_version_major * 1000000
    repo_version_numeric += repo_version_minor * 1000
    repo_version_numeric += repo_version_patch

    if code_version_numeric >= repo_version_numeric:
        config.bot.logger.info('Tootbot v%s.%s.%s is up to date.',
                               CODE_VERSION_MAJOR, CODE_VERSION_MINOR, CODE_VERSION_PATCH)
    else:
        config.bot.logger.warning('New version of Tootbot (v%s.%s.%s) is available!',
                                  repo_version_major, repo_version_minor, repo_version_patch)
        config.bot.logger.warning('(You have v%s.%s.%s)',
                                  CODE_VERSION_MAJOR, CODE_VERSION_MINOR, CODE_VERSION_PATCH)
        config.bot.logger.warning('Latest available at: https://gitlab.com/marvin8/tootbot/')
except (requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError) as update_check_error:
    config.bot.logger.info('while checking for updates we got this error: %s', update_check_error)

mastodon_publisher = MastodonPublisher(config=config)
healthcheck = HealthChecks(config=config)
reddit = RedditHelper(config=config)
media_helper = LinkedMediaHelper(config=config)

# Set the command line window title on Windows
if os.name == 'nt':
    try:
        # Set title with just Mastodon username
        os.system('title ' + mastodon_publisher.userinfo['username'] +
                  '@' + config.mastodon_config.domain + ' - Tootbot')
    except OSError:
        os.system('title Tootbot')

# Run the main script
while True:
    if config.health.enabled:
        healthcheck.check_start()

    reddit_posts = {}
    for subreddit in config.subreddits:
        reddit_posts[subreddit.tags] = reddit.get_reddit_posts(subreddit.name)
    mastodon_publisher.make_post(reddit_posts, reddit, media_helper)

    if config.mastodon_config.delete_after > 0:
        config.bot.logger.info('Deleting Toots older than %s days',
                               config.mastodon_config.delete_after)
        mastodon_publisher.delete_toots(older_than_days=config.mastodon_config.delete_after)
    else:
        config.bot.logger.info('Deleting old toots disabled')

    if config.health.enabled:
        healthcheck.check_ok()

    if config.bot.run_once_only:
        config.bot.logger.info('Exiting because RunOnceOnly is set to %s', config.bot.run_once_only)
        sys.exit(0)

    config.bot.logger.info('Sleeping for %s seconds', config.bot.delay_between_posts)
    time.sleep(config.bot.delay_between_posts)

    if config.mastodon_config.throttling_enabled:
        extra_sleep = 1
        sleep_time_elapsed = config.bot.delay_between_posts
        while extra_sleep <= config.mastodon_config.number_of_errors and \
                sleep_time_elapsed <= config.mastodon_config.throttling_max_delay:
            if config.health.enabled:
                healthcheck.check(data='Extra wait due to Mastodon API error')
            config.bot.logger.info('Extra sleep #%s due to Mastodon API error(s)', extra_sleep)
            time.sleep(config.bot.delay_between_posts)
            sleep_time_elapsed += config.bot.delay_between_posts
            extra_sleep += 1

    config.bot.logger.info('Restarting main process...')
