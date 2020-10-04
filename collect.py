"""
This module contains helper classes and methods to assist with the collection of content
to be posted to Mastodon and/or Twitter
"""

import configparser
import os
import sys

import praw
import prawcore.exceptions


class RedditHelper:
    """
    RedditHelper provides methods to collect data / content from reddit to then post on
    Mastodon/Twitter
    """

    # Check if reddit access details in 'reddit.secret' file has already been set-up and load it.
    # otherwise guide user through setting it up.
    def __init__(self, logger, user_agent='Tootbot', config_file='reddit.secret'):
        self.logger = logger
        self.user_agent = user_agent
        self.allow_nsfw = False
        self.allow_self = False
        self.allow_spoilers = False

        reddit_config = configparser.ConfigParser()
        if not os.path.exists(config_file):
            logger.warning('Reddit API keys not found. (See wiki if you need help).')
            # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
            reddit_agent = ''.join(input("[ .. ] Enter Reddit agent: ").split())
            reddit_client_secret = ''.join(input("[ .. ] Enter Reddit client secret: ").split())
            # Make sure authentication is working
            try:
                reddit_client = praw.Reddit(user_agent=self.user_agent, client_id=reddit_agent,
                                            client_secret=reddit_client_secret)
                reddit_client.subreddit('announcements')
                # It worked, so save the keys to a file
                reddit_config['Reddit'] = {'Agent': reddit_agent,
                                           'ClientSecret': reddit_client_secret,
                                           }
                with open(config_file, 'w') as new_reddit_secrets_file:
                    reddit_config.write(new_reddit_secrets_file)
                new_reddit_secrets_file.close()
            except prawcore.exceptions.ResponseException as reddit_exception:
                logger.error('Error while logging into Reddit: %s', reddit_exception)
                logger.error('Tootbot cannot continue, now shutting down')
                sys.exit(1)
        else:
            # Read API keys from secret file
            reddit_config.read(config_file)

        self.reddit_connection = praw.Reddit(user_agent=self.user_agent,
                                             client_id=reddit_config['Reddit']['Agent'],
                                             client_secret=reddit_config['Reddit']['ClientSecret'])

    def get_reddit_posts(self, subreddit, limit=10):
        """
        get_reddit_posts reads up to "limit" number of posts from a given subreddit and returns
        them as a dict of

        Arguments:
            subreddit (string): name of subreddit (without leading "r/") to collect posts from
            limit (int): maximum number of posts to return (default 10)

        Returns:
            posts (dict): of posts to subreddit. each entry has a key of subreddit post-id
        """
        posts = {}
        self.logger.info('Getting posts from Subreddit: "%s"' % subreddit)
        subreddit_info = self.reddit_connection.subreddit(subreddit)
        try:
            for submission in subreddit_info.hot(limit=limit):

                if submission.over_18 and self.allow_nsfw is False:
                    # Skip over NSFW posts if they are disabled in the config file
                    self.logger.info('Skipping %s because it is marked as NSFW' % submission.id)
                    continue

                if submission.is_self and self.allow_self is False:
                    # Skip over NSFW posts if they are disabled in the config file
                    self.logger.info('Skipping %s because it is a self post' % submission.id)
                    continue

                if submission.spoiler and self.allow_spoilers is False:
                    # Skip over posts marked as spoilers if they are disabled in
                    # the config file
                    self.logger.info('Skipping %s because it is marked as a spoiler', submission.id)
                    continue

                if submission.stickied:
                    self.logger.info('Skipping %s because it is stickied' % submission.id)
                    continue

                # Create dict
                posts[submission.id] = submission
        except prawcore.exceptions.ResponseException as reddit_exception:
            self.logger.warn('Encountered and error getting reddit posts: $%', reddit_exception)

        return posts
