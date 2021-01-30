"""
This module contains helper classes and methods to assist with the collection of content
to be posted to Mastodon and/or Twitter
"""
# pylint: disable=E1136

import configparser
import hashlib
import logging
import os
import re
import sys
from typing import List
from typing import Optional
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import praw
import prawcore.exceptions
import requests
from PIL import Image as PILImage
from bs4 import BeautifulSoup
from gfycat.client import GfycatClient
from gfycat.error import GfycatClientError
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError
from praw.models import Submission

from control import Configuration

FATAL_TOOTBOT_ERROR = 'Tootbot cannot continue, now shutting down'


# Function for downloading images from a URL to media folder
def save_file(img_url: str, file_path: str, logger: logging.Logger) -> Optional[str]:
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
    def __init__(self, config: Configuration,
                 user_agent: str = 'Tootbot',
                 config_file: str = 'reddit.secret'):
        self.logger = config.bot.logger
        self.user_agent = user_agent
        self.reddit_config = config.reddit
        self.global_hash_tags = config.bot.hash_tags
        self.promo_every = config.promo.every
        self.promo_message = config.promo.message

        reddit_config = configparser.ConfigParser()
        if not os.path.exists(config_file):
            self.logger.warning('Reddit API keys not found. (See wiki if you need help).')
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
                self.logger.error('Error while logging into Reddit: %s', reddit_exception)
                self.logger.error(FATAL_TOOTBOT_ERROR)
                sys.exit(1)
        else:
            # Read API keys from secret file
            reddit_config.read(config_file)

        self.reddit_connection = praw.Reddit(user_agent=self.user_agent,
                                             client_id=reddit_config['Reddit']['Agent'],
                                             client_secret=reddit_config['Reddit']['ClientSecret'])

    def get_reddit_posts(self, subreddit: str, limit: int = 10) -> dict:
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

                if submission.over_18 and not self.reddit_config.nsfw_allowed:
                    # Skip over NSFW posts if they are disabled in the config file
                    self.logger.info('Skipping %s, it is marked as NSFW', submission.id)
                    continue

                if submission.is_self and not self.reddit_config.self_posts:
                    # Skip over NSFW posts if they are disabled in the config file
                    self.logger.info('Skipping %s, it is a self post', submission.id)
                    continue

                if submission.spoiler and not self.reddit_config.spoilers:
                    # Skip over posts marked as spoilers if they are disabled in
                    # the config file
                    self.logger.info('Skipping %s, it is marked as a spoiler', submission.id)
                    continue

                if submission.stickied and not self.reddit_config.stickied_allowed:
                    self.logger.info('Skipping %s, it is stickied', submission.id)
                    continue

                # Create dict
                posts[submission.id] = submission
        except prawcore.exceptions.ResponseException as reddit_exception:
            self.logger.warning('Encountered and error getting reddit posts: $%', reddit_exception)

        return posts

    def get_caption(self, submission: Submission, max_len: int,
                    add_hash_tags: str = None, promo_message: str = None) -> str:
        """
        get_caption returns the text to be posted to mastodon. This is determined from the text of
        the reddit submission, if a promo message should be included, and any hash tags

        Arguments:
            submission (Submission): PRAW Submission object for the reddit post we are determining
            the mastodon toot text for.
            max_len: (int): The maximum length the text for the mastodon toot can be.
            add_hash_tags (str): additional hash tags to be added to global hash tags defined in
            config file. The hash tags must be comma delimited
            promo_message (str): Any promo message that must be added to end of caption. Set to None
            if no promo message to be added
        """
        # Create string of hashtags
        hashtag_string = ''
        promo_string = ''
        hashtags_for_post = self.global_hash_tags

        # Workout hash tags for post
        if add_hash_tags is not None:
            hashtags_for_subreddit = [x.strip() for x in add_hash_tags.split(',')]
            hashtags_for_post = hashtags_for_subreddit + self.global_hash_tags
        if hashtags_for_post:
            for tag in hashtags_for_post:
                # Add hashtag to string, followed by a space for the next one
                hashtag_string += '#' + tag + ' '

        if promo_message:
            promo_string = ' \n \n%s' % self.promo_message
        caption_max_length = max_len
        caption_max_length -= len(submission.shortlink) - len(hashtag_string) - len(promo_string)

        # Create contents of the Mastodon post
        if len(submission.title) < caption_max_length:
            caption = submission.title + ' '
        else:
            caption = submission.title[caption_max_length - 2] + '... '
        caption += hashtag_string + submission.shortlink + promo_string
        return caption


class LinkedMediaHelper:
    """
    ImgurHelper provides methods to collect data / content from Imgur and Gfycat
    """

    def __init__(self, config: Configuration,
                 imgur_secrets: str = 'imgur.secret',
                 gfycat_secrets: str = 'gfycat.secret',
                 ):
        self.logger = config.bot.logger
        self.save_dir = config.media.folder

        try:
            imgur_config = self._get_imgur_secrets(imgur_secrets)
            self.imgur_client = ImgurClient(imgur_config['Imgur']['ClientID'],
                                            imgur_config['Imgur']['ClientSecret'],
                                            )

            gfycat_config = self._get_gfycat_secrets(gfycat_secrets)
            self.gfycat_client = GfycatClient(gfycat_config['Gfycat']['ClientID'],
                                              gfycat_config['Gfycat']['ClientSecret'],
                                              )

        except ImgurClientError as imgur_error:
            self.logger.error('Error on creating ImgurClient: %s', imgur_error)
            self.logger.error(FATAL_TOOTBOT_ERROR)
            sys.exit(1)
        except GfycatClientError as gfycat_error:
            self.logger.error('Error on creating GfycatClient: %s', gfycat_error)
            self.logger.error(FATAL_TOOTBOT_ERROR)
            sys.exit(1)

    def _get_gfycat_secrets(self, gfycat_secrets: str) -> configparser.ConfigParser:
        """
        _get_gfycat_secrets checks if the Gfycat api secrets file exists.
        - If the file exists, this methods reads the the files and returns the secrets in as a dict.
        - If the file doesn't exist it asks the user over stdin to supply these values and then
          saves them into the gfycat_secrets file

        Arguments:
            gfycat_secrets (string): file name of secrets file for API credentials

        Returns:
            imgur_config (dict): Dictionary containing the client id and client secret needed to
            login to Gfycat
        """

        if not os.path.exists(gfycat_secrets):
            self.logger.warning('Gfycat API keys not found. (See wiki if you need help).')

            # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
            gfycat_client_id = ''.join(input("[ .. ] Enter Gfycat client ID: ").split())
            gfycat_client_secret = ''.join(input("[ .. ] Enter Gfycat client secret: ").split())
            # Make sure authentication is working
            try:
                gfycat_client = GfycatClient(gfycat_client_id, gfycat_client_secret)

                # If this call doesn't work, it'll throw an ImgurClientError
                gfycat_client.query_gfy('oddyearlyhorsefly')
                # It worked, so save the keys to a file
                gfycat_config = configparser.ConfigParser()
                gfycat_config['Gfycat'] = {'ClientID': gfycat_client_id,
                                           'ClientSecret': gfycat_client_secret,
                                           }
                with open(gfycat_secrets, 'w') as file:
                    gfycat_config.write(file)
                file.close()
            except GfycatClientError as gfycat_error:
                self.logger.error('Error while logging into Gfycat: %s', gfycat_error)
                self.logger.error(FATAL_TOOTBOT_ERROR)
                sys.exit(1)
        else:
            # Read API keys from secret file
            gfycat_config = configparser.ConfigParser()
            gfycat_config.read(gfycat_secrets)

        return gfycat_config

    def _get_imgur_secrets(self, imgur_secrets: str) -> configparser.ConfigParser:
        """
        _get_imgur_secrets checks if the Imgur api secrets file exists.
        - If the file exists, this methods reads the the files and returns the secrets in as a dict.
        - If the file doesn't exist it asks the user over stdin to supply these values and then
          saves them into the imgur_secrets file

        Arguments:
            imgur_secrets (string): file name of secrets file for API credentials

        Returns:
            imgur_config (dict): Dictionary containing the client id and client secret needed to
            login to Imgur
        """

        if not os.path.exists(imgur_secrets):
            self.logger.warning('Imgur API keys not found. (See wiki if you need help).')

            # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
            imgur_client_id = ''.join(input("[ .. ] Enter Imgur client ID: ").split())
            imgur_client_secret = ''.join(input("[ .. ] Enter Imgur client secret: ").split())
            # Make sure authentication is working
            try:
                imgur_client = ImgurClient(imgur_client_id, imgur_client_secret)

                # If this call doesn't work, it'll throw an ImgurClientError
                imgur_client.get_album('dqOyj')
                # It worked, so save the keys to a file
                imgur_config = configparser.ConfigParser()
                imgur_config['Imgur'] = {'ClientID': imgur_client_id,
                                         'ClientSecret': imgur_client_secret,
                                         }
                with open(imgur_secrets, 'w') as file:
                    imgur_config.write(file)
                file.close()
            except ImgurClientError as imgur_error:
                self.logger.error('Error while logging into Imgur: %s', imgur_error)
                self.logger.error(FATAL_TOOTBOT_ERROR)
                sys.exit(1)
        else:
            # Read API keys from secret file
            imgur_config = configparser.ConfigParser()
            imgur_config.read(imgur_secrets)

        return imgur_config

    def get_imgur_image(self, img_url: str, max_images: int = 4) -> List[str]:
        """
        get_imgur_image downloads images from imgur.

        Arguments:
            img_url: url of imgur image to download
            max_images: maximum number of images to download and process, Defaults to 4

        Returns:
            file_paths (string): path to downloaded image or None if no image was downloaded
        """

        # Working demo of regex: https://regex101.com/r/G29uGl/2
        regex = r"(?:.*)imgur\.com(?:\/gallery\/|\/a\/|\/)(.*?)(?:\/.*|\.|$)"
        regex_match = re.search(regex, img_url, flags=0)

        if not regex_match:
            self.logger.error('Could not identify Imgur image/gallery ID at: %s', img_url)
            return []

        # Get the Imgur image/gallery ID
        imgur_id = regex_match.group(1)

        image_urls = self._get_image_urls(img_url, imgur_id)

        # Download and process individual images (up to max_images)
        imgur_paths = []
        for image_url in image_urls:
            # If the URL is a GIFV or MP4 link, change it to the GIF version
            file_extension = os.path.splitext(image_url)[-1].lower()
            if file_extension == '.gifv':
                file_extension = '.gif'
                image_url = image_url.replace('.gifv', '.gif')
            elif file_extension == '.mp4':
                file_extension = '.gif'
                image_url = image_url.replace('.mp4', '.gif')

            # Download the image
            file_path = self.save_dir + '/' + imgur_id + '_' + str(
                len(imgur_paths)) + file_extension
            self.logger.info('Downloading Imgur image at URL %s to %s', image_url, file_path)
            current_image = save_file(image_url, file_path, self.logger)

            # Imgur will sometimes return a single-frame thumbnail
            # instead of a GIF, so we need to check for this
            if file_extension != '.gif' or self._check_imgur_gif(file_path):
                imgur_paths.append(current_image)

            if len(imgur_paths) == max_images:
                break

        return imgur_paths

    def _get_image_urls(self, img_url: str, imgur_id: str) -> List[str]:
        """
        _get_image_urls builds a list of urls of all Imgur images identified by imgur_id

        Arguments:
            img_url: URL to IMGUR post
            imgur_id: ID for IMGUR post

        Returns:
            imgur_urls: List of urls to images of Imgur post identified byr imgur_id
        """
        image_urls = []
        try:
            if any(s in img_url for s in ('/a/', '/gallery/')):  # Gallery links
                self.logger.info('Imgur link points to gallery: %s', img_url)
                images = self.imgur_client.get_album_images(imgur_id)
                for image in images:
                    image_urls.append(image.link)
            else:  # Single image
                image_urls = [self.imgur_client.get_image(imgur_id).link]
        except ImgurClientError as imgur_error:
            self.logger.error('Could not get information from imgur: %s', imgur_error)
        return image_urls

    def _check_imgur_gif(self, file_path: str) -> bool:
        """
        _check_imgur_gif checks if a file downloaded from imgur is indeed a gif. If file is not
        a gif, remove the file.

        Arguments:
            file_path: file name and path to downloaded image

        Returns:
             True if downloaded image is indeed a GIF, otherwise returns False
        """
        img = PILImage.open(file_path)
        mime = PILImage.MIME[img.format]
        img.close()

        if mime != 'image/gif':
            self.logger.warning('Imgur: not a GIF, not posting')
            try:
                os.remove(file_path)
            except OSError as remove_error:
                self.logger.error('Error while deleting media file: %s', remove_error)
            return False

        return True

    def get_gfycat_image(self, img_url: str) -> Optional[str]:
        """
        get_gfycat_image downloads full resolution images from gfycat.

        Arguments:
            img_url (string): url of gfycat image to download

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        gfycat_url = ""
        file_path = self.save_dir + '/'
        try:
            gfycat_name = os.path.basename(urlsplit(img_url).path)
            response = requests.get(img_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            for tag in soup.find_all("source", src=True):
                src = tag['src']
                if "giant" in src and "mp4" in src:
                    gfycat_url = src
            file_path += gfycat_name + '.mp4'
        except (requests.ConnectionError,
                requests.Timeout,
                requests.HTTPError,
                GfycatClientError) as gfycat_error:
            self.logger.error('Error downloading Gfycat link: %s', gfycat_error)
            return None

        if gfycat_url == '':
            self.logger.debug('Empty Gfycat URL; no attachment to download')
            return None

        self.logger.info('Downloading Gfycat at URL %s to %s', gfycat_url, file_path)
        return save_file(gfycat_url, file_path, self.logger)

    def get_reddit_image(self, img_url: str) -> str:
        """
        get_reddit_image downloads full resolution images from i.reddit or reddituploads.

        Arguments:
            img_url (string): url of imgur image to download

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        file_name = os.path.basename(urlsplit(img_url).path)
        file_extension = os.path.splitext(img_url)[1].lower()
        # Fix for issue with i.reddituploads.com links not having a
        # file extension in the URL
        if not file_extension:
            file_extension += '.jpg'
            file_name += '.jpg'
            img_url += '.jpg'
        # Download the file
        file_path = self.save_dir + '/' + file_name
        self.logger.info('Downloading file at URL %s to %s, file type identified as %s',
                         img_url,
                         file_path,
                         file_extension,
                         )
        return save_file(img_url, file_path, self.logger)

    def get_reddit_gallery(self, reddit_post: Submission, max_images: int = 4) -> List[str]:
        """
        get_reddit_gallery downloads up to max_images images from a reddit gallery post and returns
        a List of file_paths downloaded images

        Arguments:
            reddit_post (reddit_post):  reddit post / submission object
            max_images (int): [optional] maximum number of images to download. Default is 4

        Returns:
            file_paths (List[str]) a list of the paths to downloadeed files. If no images have been
            downloaded, and empty list will be returned.
        """
        file_paths = []
        for item in sorted(reddit_post.gallery_data['items'], key=lambda x: x['id']):
            media_id = item['media_id']
            meta = reddit_post.media_metadata[media_id]
            self.logger.debug('Media Metadata: %s', meta)
            if 'e' in meta and meta['e'] == 'Image':
                source = meta['s']
                save_path = self.save_dir + '/' + media_id + '.' + meta['m'].split('/')[1]
                self.logger.info('Gallery file_path, source: %s - %s', save_path, source['u'])
                self.logger.debug('A[%4dx%04d] %s' % (source['x'], source['y'], source['u']))
                file_paths.append(save_file(source['u'], save_path, self.logger))

                if len(file_paths) == max_images:
                    break

        return file_paths

    def get_reddit_video(self, reddit_post: Submission) -> str:
        """
        get_reddit_video downloads full resolution video from i.reddit or reddituploads.

        Arguments:
            reddit_post (reddit_post): reddit post / submission object

        Returns:
            file_path (string): path to downloaded video or None if no image was downloaded
        """
        # Get URL for MP4 version of reddit video
        video_url = reddit_post.media['reddit_video']['fallback_url']
        file_path = self.save_dir + '/' + reddit_post.id + '.mp4'
        self.logger.info('Downloading Reddit video at URL %s to %s', video_url, file_path)
        return save_file(video_url, file_path, self.logger)

    def get_giphy_image(self, img_url: str) -> Optional[str]:
        """
        get_giphy_image downloads full or low resolution image from giphy

        Arguments:
            img_url (string): url of giphy image to download

        Returns:
            file_path (string): path to downloaded image or None if no image was downloaded
        """
        # Working demo of regex: https://regex101.com/r/o8m1kA/2
        regex = r"https?://((?:.*)giphy\.com/media/|giphy.com/gifs/|i.giphy.com/)(.*-)?(\w+)(/|\n)"
        match = re.search(regex, img_url, flags=0)
        if not match:
            self.logger.error('Could not identify Giphy ID in this URL: %s', img_url)
            return None

        # Get the Giphy ID
        giphy_id = match.group(3)
        # Download the MP4 version of the GIF
        giphy_url = 'https://media.giphy.com/media/' + giphy_id + '/giphy.mp4'
        file_path = self.save_dir + '/' + giphy_id + 'giphy.mp4'
        giphy_file = save_file(giphy_url, file_path, self.logger)
        self.logger.info('Downloading Giphy at URL %s to %s', giphy_url, file_path)

        return giphy_file

    def get_generic_image(self, img_url: str) -> Optional[str]:
        """
        get_generic_image downloads image or video from a generic url to a media file.

        Arguments:
            img_url (string): url to image or video file

        Returns:
            file_path (string): path to downloaded video or None if no image was downloaded
        """
        # First check if URL starts with http:// or https://
        regex = r"^https?://"
        match = re.search(regex, img_url, flags=0)
        if not match:
            self.logger.info('Post link is not a full link: %s', img_url)
            return None

        # Check if URL is an image or MP4 file, based on the MIME type
        image_formats = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'video/mp4')
        try:
            img_site = urlopen(img_url)
        except (URLError, UnicodeEncodeError) as url_error:
            self.logger.error('Error while opening URL %s', url_error)
            return None

        meta = img_site.info()
        if meta["content-type"] not in image_formats:
            self.logger.error('URL does not point to a valid image file: %s', img_url)
            return None

        # URL appears to be an image, so download it
        file_name = os.path.basename(urlsplit(img_url).path)
        file_path = self.save_dir + '/' + file_name
        self.logger.info('Downloading file at URL %s to %s', img_url, file_path)
        return save_file(img_url, file_path, self.logger)


class MediaAttachment:
    """
    MediaAttachment contains code to retrieve the appropriate images or videos to include in a
    s reddit post to be shared on Mastodon or Twitter
    """

    def __init__(self, reddit_post: Submission, image_helper: LinkedMediaHelper,
                 logger: logging.Logger):

        self.media_paths = {}
        self.reddit_post = reddit_post
        self.media_url = self.reddit_post.url
        self.image_helper = image_helper
        self.logger = logger

        for media_path in self.get_media():
            self.logger.info('Media path for checksum calculation: %s', media_path)
            if media_path is not None:
                sha256 = hashlib.sha256()
                with open(media_path, "rb") as media_file:
                    # Read and update hash string value in blocks of 4K
                    for byte_block in iter(lambda: media_file.read(4096), b""):
                        sha256.update(byte_block)
                self.media_paths[sha256.hexdigest()] = media_path

    def destroy(self):
        """
        Removes any files downloaded and clears out the object attributes.
        """
        try:
            for checksum in self.media_paths:
                media_path = self.media_paths[checksum]
                if media_path is not None:
                    os.remove(media_path)
                    self.logger.info('Deleted media file at %s', media_path)
        except OSError as delete_error:
            self.logger.error('Error while deleting media file: %s', delete_error)

        self.media_paths = {}
        self.media_url = None

    def destroy_one_attachment(self, checksum: str):
        """
        Removes file with checksum downloaded.

        Arguments:
            checksum (string): key to media_paths dictionary for file to be removed.
        """
        try:
            media_path = self.media_paths[checksum]
            if media_path is not None:
                os.remove(media_path)
                self.logger.info('Deleted media file at %s', media_path)
            self.media_paths.pop(checksum)
        except OSError as delete_error:
            self.logger.error('Error while deleting media file: %s', delete_error)

    # Function for obtaining static images and GIFs from popular image hosts
    def get_media(self) -> List[str]:
        """
        Determines which method to call depending on which site the media_url is pointing to.
        """
        if not os.path.exists(self.image_helper.save_dir):
            os.makedirs(self.image_helper.save_dir)
            self.logger.info('Media folder not found, created new folder: %s',
                             self.image_helper.save_dir)

        file_paths = []

        # Download and save the linked image
        if hasattr(self.reddit_post, "is_gallery"):
            self.logger.debug('%s is a gallery post', self.reddit_post.id)
            file_paths.extend(self.image_helper.get_reddit_gallery(self.reddit_post))
        elif any(s in self.media_url for s in ('i.redd.it', 'i.reddituploads.com')):
            file_paths.append(self.image_helper.get_reddit_image(self.media_url))
        elif 'v.redd.it' in self.media_url and not self.reddit_post.media:
            self.logger.error('Reddit API returned no media for this URL: %s', self.media_url)
        elif 'v.redd.it' in self.media_url:
            file_paths.append(self.image_helper.get_reddit_video(self.reddit_post))

        elif 'imgur.com' in self.media_url:
            self.logger.info('Reddit post %s links to Imgur', self.reddit_post.id)
            file_paths.extend(self.image_helper.get_imgur_image(self.media_url))

        elif 'gfycat.com' in self.media_url:  # Gfycat
            file_paths.append(self.image_helper.get_gfycat_image(self.media_url))

        elif 'giphy.com' in self.media_url:  # Giphy
            file_paths.append(self.image_helper.get_giphy_image(self.media_url))

        else:
            file_paths.append(self.image_helper.get_generic_image(self.media_url))

        return file_paths
