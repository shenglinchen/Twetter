import hashlib
import os
import re
import urllib
import urllib.request
from urllib.request import urlopen

import requests


# Implementing class for media attachment
class MediaAttachment:
    LOW_RES = 1
    HIGH_RES = 2
    HIGH_AND_LOW_RES = 3

    def __init__(self, media_url, imgur_helper, image_dir, download_for, logger):

        self.media_path_low_res = None
        self.media_path_high_res = None
        self.media_url = media_url
        self.logger = logger

        if download_for in [self.LOW_RES, self.HIGH_AND_LOW_RES]:
            self.media_path_low_res = get_media(self.media_url,
                                                imgur_helper,
                                                image_dir,
                                                logger)
        if download_for in [self.HIGH_RES, self.HIGH_AND_LOW_RES]:
            self.media_path_high_res = get_hd_media(self.media_url,
                                                    imgur_helper,
                                                    image_dir,
                                                    logger)

        sha256 = hashlib.sha256()
        if self.media_path_low_res is not None:
            with open(self.media_path_low_res, "rb") as f:
                # Read and update hash string value in blocks of 4K
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256.update(byte_block)
        self.check_sum_low_res = sha256.hexdigest()

        sha256 = hashlib.sha256()
        if self.media_path_high_res is not None:
            with open(self.media_path_high_res, "rb") as f:
                # Read and update hash string value in blocks of 4K
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256.update(byte_block)
        self.check_sum_high_res = sha256.hexdigest()

    def destroy(self):

        try:
            if self.media_path_high_res is not None:
                os.remove(self.media_path_high_res)
                if self.logger is not None:
                    self.logger.info('Deleted media file at %s' % self.media_path_high_res)
            if self.media_path_low_res is not None:
                os.remove(self.media_path_low_res)
                if self.logger is not None:
                    self.logger.info('Deleted media file at %s' % self.media_path_low_res)
        except BaseException as e:
            if self.logger is not None:
                self.logger.error('Error while deleting media file: %s' % e)

        self.media_path_high_res = None
        self.media_path_low_res = None
        self.media_url = None
        self.check_sum_high_res = None


# Function for opening file as string of bytes
def file_as_bytes(file):
    with file:
        return file.read()


# Function for downloading images from a URL to media folder
def save_file(img_url, file_path, logger):
    resp = requests.get(img_url, stream=True)
    if resp.status_code == 200:
        with open(file_path, 'wb') as image_file:
            for chunk in resp:
                image_file.write(chunk)
        # Return the path of the image, which is always the same since we
        # just overwrite images
        image_file.close()
        return file_path
    else:
        logger.error('File failed to download. Status code: %s' % resp.status_code)


# Function for obtaining static images and GIFs from popular image hosts
def get_media(img_url, imgur_helper, image_dir, logger):
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
        logger.info('Media folder not found, created new folder: %s' % image_dir)

    # Download and save the linked image
    if any(s in img_url for s in ('i.redd.it', 'i.reddituploads.com')):  # Reddit-hosted images
        file_name = os.path.basename(urllib.parse.urlsplit(img_url).path)
        file_extension = os.path.splitext(img_url)[-1].lower()
        # Fix for issue with i.reddituploads.com links not having a
        # file extension in the URL
        if not file_extension:
            file_extension += '.jpg'
            file_name += '.jpg'
            img_url += '.jpg'
        # Download the file
        file_path = image_dir + '/lr_' + file_name
        logger.info(
            'Downloading file at URL %s to %s, file type identified as %s' %
            (img_url, file_path, file_extension))
        img = save_file(img_url, file_path, logger)
        return img
    elif 'v.redd.it' in img_url:  # Reddit video
        logger.warn('Videos can not be uploaded to Twitter, due to API limitations')

    elif 'imgur.com' in img_url:
        return imgur_helper.get_imgur_image(img_url, image_dir)

    elif 'gfycat.com' in img_url:  # Gfycat
        return imgur_helper.get_gfycat_image_lowres(img_url, image_dir)

    elif 'giphy.com' in img_url:  # Giphy
        # Working demo of regex: https://regex101.com/r/o8m1kA/2
        regex = r"https?://((?:.*)giphy\.com/media/|giphy.com/gifs/|i.giphy.com/)(.*-)?(\w+)(/|\n)"
        m = re.search(regex, img_url, flags=0)
        if m:
            # Get the Giphy ID
            giphy_id = m.group(3)
            # Download the 2MB version because Tweepy has a 3MB
            # upload limit for GIFs
            giphy_url = 'https://media.giphy.com/media/'
            giphy_url += giphy_id + '/giphy-downsized.gif'
            file_path = image_dir + '/lr_' + giphy_id + '-downsized.gif'
            logger.info('Downloading Giphy at %s to %s' %
                        (giphy_url, file_path))
            giphy_file = save_file(giphy_url, file_path, logger)
            # Check the hash to make sure it's not a GIF saying
            # "This content is not available"
            # More info: https://github.com/corbindavenport/tootbot/issues/8
            image_hash = hashlib.md5(file_as_bytes(open(giphy_file, 'rb'))).hexdigest()
            if image_hash == '59a41d58693283c72d9da8ae0561e4e5':
                logger.warn('Giphy: no 2MB GIF version, not posted to Twitter')
            else:
                return giphy_file
        else:
            logger.error('Could not identify Giphy ID at: %s' % img_url)
    else:
        # Check if URL is an image, based on the MIME type
        image_formats = ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
        try:
            img_site = urlopen(img_url)
        except BaseException as e:
            logger.error('Error whole opening URL %s' % e)
            return
        meta = img_site.info()
        if meta["content-type"] in image_formats:
            # URL appears to be an image, so download it
            file_name = os.path.basename(urllib.parse.urlsplit(img_url).path)
            file_path = image_dir + '/lr_' + file_name
            logger.info('Downloading file at %s to %s' % (img_url, file_path))
            try:
                img = save_file(img_url, file_path, logger)
                return img
            except BaseException as e:
                logger.error('Error while downloading image %s' % e)
                return
        else:
            logger.error('URL does not point to a valid image file')


# Function for obtaining static images/GIFs, or MP4 videos if they exist,
# from popular image hosts. This is currently only used for Mastodon posts,
# because the Tweepy API doesn't support video uploads
def get_hd_media(submission, imgur_helper, image_dir, logger):
    media_url = submission.url
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
        logger.info('Media folder not found, created a new one')
    # Download and save the linked image
    if any(s in media_url for s in ('i.redd.it', 'i.reddituploads.com')):  # Reddit-hosted images
        file_name = os.path.basename(urllib.parse.urlsplit(media_url).path)
        file_extension = os.path.splitext(media_url)[-1].lower()
        # Fix for issue with i.reddituploads.com links not having a
        # file extension in the URL
        if not file_extension:
            file_extension += '.jpg'
            file_name += '.jpg'
            media_url += '.jpg'
        # Download the file
        file_path = image_dir + '/hr_' + file_name
        logger.info(
            'Downloading file at URL %s to %s, file type identified as %s' %
            (media_url, file_path, file_extension))
        img = save_file(media_url, file_path, logger)
        return img
    elif 'v.redd.it' in media_url:  # Reddit video
        if submission.media:
            # Get URL for MP4 version of reddit video
            video_url = submission.media['reddit_video']['fallback_url']
            # Download the file
            file_path = image_dir + '/hr_' + submission.id + '.mp4'
            logger.info('Downloading Reddit video at URL %s to %s' %
                        (video_url, file_path))
            return save_file(video_url, file_path, logger)
        else:
            logger.error('Reddit API returned no media for this URL: %s' % media_url)

    elif 'imgur.com' in media_url:  # Imgur
        return imgur_helper.get_imgur_image(media_url, image_dir)

    elif 'gfycat.com' in media_url:  # Gfycat
        return imgur_helper.get_gfycat_image(media_url, image_dir)

    elif 'giphy.com' in media_url:  # Giphy
        # Working demo of regex: https://regex101.com/r/o8m1kA/2
        regex = r"https?://((?:.*)giphy\.com/media/|giphy.com/gifs/|i.giphy.com/)(.*-)?(\w+)(/|\n)"
        m = re.search(regex, media_url, flags=0)
        if m:
            # Get the Giphy ID
            giphy_id = m.group(3)
            # Download the MP4 version of the GIF
            giphy_url = 'https://media.giphy.com/media/' + giphy_id + '/giphy.mp4'
            file_path = image_dir + '/hr_' + giphy_id + 'giphy.mp4'
            logger.info('Downloading Giphy at URL %s to %s' % (giphy_url, file_path))
            return save_file(giphy_url, file_path, logger)
        else:
            logger.error('Could not identify Giphy ID in this URL: %s' % media_url)
    else:
        # Check if URL is an image or MP4 file, based on the MIME type
        image_formats = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'video/mp4')
        try:
            img_site = urlopen(media_url)
        except BaseException as e:
            logger.error('Error whole opening URL %s' % e)
            return
        meta = img_site.info()
        if meta["content-type"] in image_formats:
            # URL appears to be an image, so download it
            file_name = os.path.basename(urllib.parse.urlsplit(media_url).path)
            file_path = image_dir + '/hr_' + file_name
            logger.info('Downloading file at URL %s to %s' % (media_url, file_path))
            try:
                img = save_file(media_url, file_path, logger)
                return img
            except BaseException as e:
                logger.error('Error while downloading image: %s' % e)
                return
        else:
            logger.error('URL does not point to a valid image file.')
