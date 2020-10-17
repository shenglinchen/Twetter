"""
This module contains helper classes and methods to assist with the collection of content
to be posted to Mastodon and/or Twitter
"""

import configparser
import os
import re
import sys
from urllib.parse import urlsplit

import praw
import prawcore.exceptions
import requests
from PIL import Image
from bs4 import BeautifulSoup
# from gfycat.client import GfycatClient
from gfycat.error import GfycatClientError
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError


# Function for downloading images from a URL to media folder
def save_file(img_url, file_path, logger):
    """
    Utility method to save a file located at img_url to a file located at filepath

        Arguments:
            img_url (string): url of imgur image to download
            file_path (string): directory and filename where to save the downloaded image to
            logger (logger): logger to use for logging messages

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
    """
    resp = requests.get(img_url, stream=True)
    if resp.status_code == 200:
        with open(file_path, 'wb') as image_file:
            for chunk in resp:
                image_file.write(chunk)
        # Return the path of the image, which is always the same since we
        # just overwrite images
        image_file.close()
        return file_path

    logger.error('File failed to download. Status code: %s' % resp.status_code)
    return None


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


class ImgurHelper:
    """
    ImgurHelper provides methods to collect data / content from Imgur and Gfycat
    """

    def __init__(self, logger, secrets_file='imgur.secret'):
        self.logger = logger

        # Setup and verify Imgur access
        if not os.path.exists(secrets_file):
            self.logger.warning('Imgur API keys not found. (See wiki if you need help).')

            # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
            imgur_client_id = ''.join(input("[ .. ] Enter Imgur client ID: ").split())
            imgur_client_secret = ''.join(input("[ .. ] Enter Imgur client secret: ").split())
            # Make sure authentication is working
            try:
                imgur_client_id = ImgurClient(imgur_client_id, imgur_client_secret)

                # If this call doesn't work, it'll throw an ImgurClientError
                imgur_client_id.get_album('dqOyj')
                # It worked, so save the keys to a file
                imgur_config = configparser.ConfigParser()
                imgur_config['Imgur'] = {
                    'ClientID': imgur_client_id,
                    'ClientSecret': imgur_client_secret
                }
                with open(secrets_file, 'w') as file:
                    imgur_config.write(file)
                file.close()
            except ImgurClientError as imgur_error:
                logger.error('Error while logging into Imgur: %s', imgur_error)
                logger.error('Tootbot cannot continue, now shutting down')
                sys.exit(1)
        else:
            # Read API keys from secret file
            imgur_config = configparser.ConfigParser()
            imgur_config.read(secrets_file)

        self.imgur_client = ImgurClient(imgur_config['Imgur']['ClientID'],
                                        imgur_config['Imgur']['ClientSecret'],
                                        )
        # self.gfycat_client = GfycatClient()
        self.gfycat_client = None

    def get_imgur_image(self, img_url, save_dir):
        """
        get_imgur_image downloads images from imgur.

        Arguments:
            img_url (string): url of imgur image to download
            save_dir (string): directory where to save the downloaded image to

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        # Working demo of regex: https://regex101.com/r/G29uGl/2
        regex = r"(?:.*)imgur\.com(?:\/gallery\/|\/a\/|\/)(.*?)(?:\/.*|\.|$)"
        regex_match = re.search(regex, img_url, flags=0)

        if not regex_match:
            self.logger.error('Could not identify Imgur image/gallery ID at: %s', img_url)
            return None

        # Get the Imgur image/gallery ID
        imgur_id = regex_match.group(1)
        if any(s in img_url for s in ('/a/', '/gallery/')):  # Gallery links
            images = self.imgur_client.get_album_images(imgur_id)
            # Only the first image in a gallery is used
            imgur_url = images[0].link
        else:  # Single image
            imgur_url = self.imgur_client.get_image(imgur_id).link

        # If the URL is a GIFV or MP4 link, change it to the GIF version
        file_extension = os.path.splitext(imgur_url)[-1].lower()
        if file_extension == '.gifv':
            file_extension = '.gif'
            imgur_url = imgur_url.replace('.gifv', '.gif')
        elif file_extension == '.mp4':
            file_extension = '.gif'
            imgur_url = imgur_url.replace('.mp4', '.gif')

        # Download the image
        file_path = save_dir + '/lr_' + imgur_id + file_extension
        self.logger.info('Downloading Imgur image at URL %s to %s', imgur_url, file_path)
        imgur_file = save_file(imgur_url, file_path, self.logger)

        # Imgur will sometimes return a single-frame thumbnail
        # instead of a GIF, so we need to check for this
        if file_extension == '.gif':
            # Open the file using the Pillow library
            img = Image.open(imgur_file)
            # Get the MIME type
            mime = Image.MIME[img.format]
            img.close()

            # Image is not actually a GIF, so don't post it
            if mime != 'image/gif':
                self.logger.warn('Imgur: not a GIF, not posted to Twitter')
                # Delete the image
                try:
                    os.remove(imgur_file)
                except OSError as os_error:
                    self.logger.error('Error while deleting media file: %s', os_error)
                return None

        return imgur_file

    def get_gfycat_image_lowres(self, img_url, save_dir):
        """
        get_gfycat_image_lowres downloads low resolution images from gfycat.

        Arguments:
            img_url (string): url of imgur image to download
            save_dir (string): directory where to save the downloaded image to

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        try:
            gfycat_name = os.path.basename(urlsplit(img_url).path)
            client = self.gfycat_client
            gfycat_info = client.query_gfy(gfycat_name)
        except GfycatClientError as gfycat_error:
            self.logger.error('Error downloading Gfycat link: %s', gfycat_error)
            return None

        # Download the 2MB version because Tweepy has 3MB upload limit for GIFs
        gfycat_url = gfycat_info['gfyItem']['max2mbGif']
        file_path = save_dir + '/lr_' + gfycat_name + '.gif'
        self.logger.info('Downloading Gfycat at URL %s to %s', gfycat_url, file_path)
        return save_file(gfycat_url, file_path, self.logger)

    def get_gfycat_image(self, img_url, save_dir):
        """
        get_gfycat_image downloads full resolution images from gfycat.

        Arguments:
            img_url (string): url of imgur image to download
            save_dir (string): directory where to save the downloaded image to

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        try:
            gfycat_name = os.path.basename(urlsplit(img_url).path)
            response = requests.get(img_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            gfycat_url = ""
            for tag in soup.find_all("source", src=True):
                src = tag['src']
                if "giant" in src and "mp4" in src:
                    gfycat_url = src
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as gfycat_error:
            self.logger.error('Error downloading Gfycat link: %s', gfycat_error)
            return None

        if gfycat_url == '':
            self.logger.debug('Empty Gfycat URL; no attachment to download')
            return None

        file_path = save_dir + '/hr_' + gfycat_name + '.mp4'
        self.logger.info('Downloading Gfycat at URL %s to %s', gfycat_url, file_path)
        return save_file(gfycat_url, file_path, self.logger)
