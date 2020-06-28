import hashlib
import os
import re
import urllib
import urllib.request
from urllib.request import urlopen

import requests
from PIL import Image
from gfycat.client import GfycatClient
from imgurpython import ImgurClient

from gfycathack import get_gfycat_mp4_download_url


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
        return


# Function for obtaining static images and GIFs from popular image hosts
def get_media(img_url, imgur_client, imgur_client_secret, image_dir, logger):
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
        file_path = image_dir + '/' + file_name
        logger.info(
            'downloading file at URL %s to %s, file type identified as %s' %
            (img_url, file_path, file_extension))
        img = save_file(img_url, file_path, logger)
        return img
    elif 'v.redd.it' in img_url:  # Reddit video
        logger.warn('Videos can not be uploaded to Twitter, due to API limitations')
        return
    elif 'imgur.com' in img_url:  # Imgur
        try:
            client = ImgurClient(imgur_client, imgur_client_secret)
        except BaseException as e:
            logger.error('Error while authenticating with Imgur: %s' % e)
            return
        # Working demo of regex: https://regex101.com/r/G29uGl/2
        regex = r"(?:.*)imgur\.com(?:\/gallery\/|\/a\/|\/)(.*?)(?:\/.*|\.|$)"
        m = re.search(regex, img_url, flags=0)
        if m:
            # Get the Imgur image/gallery ID
            imgur_id = m.group(1)
            if any(s in img_url
                   for s in ('/a/', '/gallery/')):  # Gallery links
                images = client.get_album_images(imgur_id)
                # Only the first image in a gallery is used
                imgur_url = images[0].link
            else:  # Single image
                imgur_url = client.get_image(imgur_id).link
            # If the URL is a GIFV or MP4 link, change it to the GIF version
            file_extension = os.path.splitext(imgur_url)[-1].lower()
            if file_extension == '.gifv':
                file_extension = file_extension.replace('.gifv', '.gif')
                imgur_url = imgur_url.replace('.gifv', '.gif')
            elif file_extension == '.mp4':
                file_extension = file_extension.replace('.mp4', '.gif')
                imgur_url = imgur_url.replace('.mp4', '.gif')
            # Download the image
            file_path = image_dir + '/' + imgur_id + file_extension
            logger.info('Downloading Imgur image at URL %s to %s' %
                        (imgur_url, file_path))
            imgur_file = save_file(imgur_url, file_path, logger)
            # Imgur will sometimes return a single-frame thumbnail
            # instead of a GIF, so we need to check for this
            if file_extension == '.gif':
                # Open the file using the Pillow library
                img = Image.open(imgur_file)
                # Get the MIME type
                mime = Image.MIME[img.format]
                if mime == 'image/gif':
                    # Image is indeed a GIF, so it can be posted
                    img.close()
                    return imgur_file
                else:
                    # Image is not actually a GIF, so don't post it
                    logger.warn('Imgur: not a GIF, not posted to Twitter')
                    img.close()
                    # Delete the image
                    try:
                        os.remove(imgur_file)
                    except BaseException as e:
                        logger.error('Error while deleting media file: %s' % e)
                    return
            else:
                return imgur_file
        else:
            logger.error('Could not identify Imgur image/gallery ID at: %s' % img_url)
            return
    elif 'gfycat.com' in img_url:  # Gfycat
        try:
            gfycat_name = os.path.basename(urllib.parse.urlsplit(img_url).path)
            client = GfycatClient(imgur_client, imgur_client_secret)
            gfycat_info = client.query_gfy(gfycat_name)
        except BaseException as e:
            logger.error('Error downloading Gfycat link: %s' % e)
            return
        # Download the 2MB version because Tweepy has 3MB upload limit for GIFs
        gfycat_url = gfycat_info['gfyItem']['max2mbGif']
        file_path = image_dir + '/' + gfycat_name + '.gif'
        logger.info('Downloading Gfycat at URL %s to %s' %
                    (gfycat_url, file_path))
        gfycat_file = save_file(gfycat_url, file_path, logger)
        return gfycat_file
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
            file_path = image_dir + '/' + giphy_id + '-downsized.gif'
            logger.info('Downloading Giphy at %s to %s' %
                        (giphy_url, file_path))
            giphy_file = save_file(giphy_url, file_path, logger)
            # Check the hash to make sure it's not a GIF saying
            # "This content is not available"
            # More info: https://github.com/corbindavenport/tootbot/issues/8
            image_hash = hashlib.md5(file_as_bytes(open(giphy_file, 'rb'))).hexdigest()
            if image_hash == '59a41d58693283c72d9da8ae0561e4e5':
                logger.warn('Giphy: no 2MB GIF version, not posted to Twitter')
                return
            else:
                return giphy_file
        else:
            logger.error('Could not identify Giphy ID at: %s' % img_url)
            return
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
            file_path = image_dir + '/' + file_name
            logger.info('Downloading file at %s to %s' % (img_url, file_path))
            try:
                img = save_file(img_url, file_path, logger)
                return img
            except BaseException as e:
                logger.error('Error while downloading image %s' % e)
                return
        else:
            logger.error('URL does not point to a valid image file')
            return


# Function for obtaining static images/GIFs, or MP4 videos if they exist,
# from popular image hosts. This is currently only used for Mastodon posts,
# because the Tweepy API doesn't support video uploads
def get_hd_media(submission, imgur_client, imgur_client_secret, image_dir, logger):
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
        file_path = image_dir + '/' + file_name
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
            file_path = image_dir + '/' + submission.id + '.mp4'
            logger.info('Downloading Reddit video at URL %s to %s' %
                        (video_url, file_path))
            video = save_file(video_url, file_path, logger)
            return video
        else:
            logger.error('Reddit API returned no media for this URL: %s' % media_url)
            return
    elif 'imgur.com' in media_url:  # Imgur
        try:
            client = ImgurClient(imgur_client, imgur_client_secret)
        except BaseException as e:
            logger.error('Error while authenticating with Imgur: %s' % e)
            return
        # Working demo of regex: https://regex101.com/r/G29uGl/2
        regex = r"(?:.*)imgur\.com(?:\/gallery\/|\/a\/|\/)(.*?)(?:\/.*|\.|$)"
        m = re.search(regex, media_url, flags=0)
        if m:
            # Get the Imgur image/gallery ID
            giphy_id = m.group(1)
            if any(s in media_url
                   for s in ('/a/', '/gallery/')):  # Gallery links
                images = client.get_album_images(giphy_id)
                # Only the first image in a gallery is used
                imgur_url = images[0].link
            else:  # Single image/GIF
                if client.get_image(giphy_id).type == 'image/gif':
                    # If the image is a GIF, use the MP4 version
                    imgur_url = client.get_image(giphy_id).mp4
                else:
                    imgur_url = client.get_image(giphy_id).link
            file_extension = os.path.splitext(imgur_url)[-1].lower()
            # Download the image
            file_path = image_dir + '/' + giphy_id + file_extension
            logger.info(' Downloading Imgur image at URL %s to %s' % (imgur_url, file_path))
            imgur_file = save_file(imgur_url, file_path, logger)
            return imgur_file
        else:
            logger.error('Could not identify Imgur image/gallery ID at: %s' % media_url)
            return
    elif 'gfycat.com' in media_url:  # Gfycat
        gfycat_url = ""
        try:
            gfycat_name = os.path.basename(urllib.parse.urlsplit(media_url).path)
            gfycat_url = get_gfycat_mp4_download_url(media_url, logger)
        except BaseException as e:
            logger.error('Error downloading Gfycat link: %s' % e)
            return
        if gfycat_url == '':
            logger.debug('Empty Gfycat URL for %s; no attachment to download' % submission.id)
            return
        file_path = image_dir + '/' + gfycat_name + '.mp4'
        logger.info('Downloading Gfycat at URL %s to %s' % (gfycat_url, file_path))
        gfycat_file = save_file(gfycat_url, file_path, logger)
        return gfycat_file
    elif 'giphy.com' in media_url:  # Giphy
        # Working demo of regex: https://regex101.com/r/o8m1kA/2
        regex = r"https?://((?:.*)giphy\.com/media/|giphy.com/gifs/|i.giphy.com/)(.*-)?(\w+)(/|\n)"
        m = re.search(regex, media_url, flags=0)
        if m:
            # Get the Giphy ID
            giphy_id = m.group(3)
            # Download the MP4 version of the GIF
            giphy_url = 'https://media.giphy.com/media/' + giphy_id + '/giphy.mp4'
            file_path = image_dir + '/' + giphy_id + 'giphy.mp4'
            logger.info('Downloading Giphy at URL %s to %s' % (giphy_url, file_path))
            giphy_file = save_file(giphy_url, file_path, logger)
            return giphy_file
        else:
            logger.error('Could not identify Giphy ID in this URL: %s' % media_url)
            return
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
            file_path = image_dir + '/' + file_name
            logger.info('Downloading file at URL %s to %s' % (media_url, file_path))
            try:
                img = save_file(media_url, file_path, logger)
                return img
            except BaseException as e:
                logger.error('Error while downloading image: %s' % e)
                return
        else:
            logger.error('URL does not point to a valid image file.')
            return
