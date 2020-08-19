import configparser
import csv
import distutils.util
import logging
import os
import sys
import time

import coloredlogs
import praw
import requests
import tweepy
from imgurpython import ImgurClient
from mastodon import Mastodon

from getmedia import MediaAttachment
from getmedia import get_media
from monitoring import HealthChecks
from reddit import RedditHelper

MAX_LEN_TWEET = 280
MAX_LEN_TOOT = 500


def get_caption(submission, max_len, addhashtags=None):
    global NUM_NON_PROMO_MESSAGES
    global PROMO_EVERY
    # Create string of hashtags
    hashtag_string = ''
    promo_string = ''
    hashtags_for_subreddit = [x.strip() for x in addhashtags.split(',')]
    hashtags_for_post = hashtags_for_subreddit + HASHTAGS
    if hashtags_for_post:
        for tag in hashtags_for_post:
            # Add hashtag to string, followed by a space for the next one
            hashtag_string += '#' + tag + ' '
    # Set the Mastodon max title length for 500, minus the length of the
    # shortlink and hashtags, minus one for the space between title
    # and shortlink
    if 0 < PROMO_EVERY <= NUM_NON_PROMO_MESSAGES:
        promo_string = ' \n \n%s' % PROMO_MESSAGE
        NUM_NON_PROMO_MESSAGES = 0
    caption_max_length = max_len - len(
        submission.shortlink) - len(hashtag_string) - len(promo_string) - 1
    # Create contents of the Mastodon post
    if len(submission.title) < caption_max_length:
        caption = submission.title + ' '
    else:
        caption = submission.title[caption_max_length - 3] + '... '
    caption += hashtag_string + submission.shortlink + promo_string
    return caption


def duplicate_check(identifier):
    value = False
    with open(CACHE_CSV, 'rt', newline='') as cache_file:
        reader = csv.reader(cache_file, delimiter=',')
        for row in reader:
            if identifier in row:
                value = True
    cache_file.close()
    return value


def log_post(reddit_id, post_url, shared_url, check_sum):
    with open(CACHE_CSV, 'a', newline='') as cache_file:
        date = time.strftime("%d/%m/%Y") + ' ' + time.strftime("%H:%M:%S")
        cache_csv_writer = csv.writer(cache_file, delimiter=',')
        cache_csv_writer.writerow([reddit_id, date, post_url, shared_url, check_sum])
    cache_file.close()


def make_post(posts):
    global NUM_NON_PROMO_MESSAGES
    break_to_mainloop = False
    for additional_hashtags, source_posts in posts.items():
        if break_to_mainloop:
            break

        for post in source_posts:
            # Grab post details from dictionary
            post_id = source_posts[post].id
            shared_url = source_posts[post].url
            if not (duplicate_check(post_id) or
                    duplicate_check(shared_url)):
                logger.debug('Processing reddit post: %s' % (source_posts[post]))
                # Post on Twitter
                if POST_TO_TWITTER:
                    # Download Twitter-compatible version of media file
                    # (static image or GIF under 3MB)
                    media_file = get_media(shared_url, IMGUR_CLIENT, IMGUR_CLIENT_SECRET, IMAGE_DIR, logger)
                    # Make sure the post contains media,
                    # if MEDIA_POSTS_ONLY in config is set to True
                    if (((MEDIA_POSTS_ONLY is True) and media_file) or
                            (MEDIA_POSTS_ONLY is False)):
                        try:
                            twitter_auth = tweepy.OAuthHandler(CONSUMER_KEY,
                                                               CONSUMER_SECRET)
                            twitter_auth.set_access_token(ACCESS_TOKEN,
                                                          ACCESS_TOKEN_SECRET)
                            twitter_api = tweepy.API(twitter_auth)
                            NUM_NON_PROMO_MESSAGES += 1
                            # Generate post caption
                            caption = get_caption(source_posts[post], MAX_LEN_TWEET)
                            # Post the tweet
                            if media_file:
                                logger.info('Posting this on Twitter with media %s' % caption)
                                tweet = twitter_api.update_with_media(filename=media_file, status=caption)
                                # Clean up media file
                                try:
                                    os.remove(media_file)
                                    logger.info('Deleted media file at %s' % media_file)
                                except BaseException as e:
                                    logger.error('Error while deleting media file: %s' % e)
                            else:
                                logger.info('Posting this on Twitter: %s' % caption)
                                tweet = twitter_api.update_status(status=caption)
                            # Log the tweet
                            log_post(
                                post_id, 'https://twitter.com/' +
                                         twitter_username + '/status/' + tweet.id_str + '/',
                                shared_url,
                                '')
                        except BaseException as e:
                            logger.error('Error while posting tweet: %s' % e)
                            # Log the post anyways
                            log_post(post_id, 'Error while posting tweet: %s' % e, '', '')
                    else:
                        logger.warning(
                            'Twitter: Skipping %s because non-media posts are disabled or the media file was not found'
                            % post_id)
                        # Log the post anyways
                        log_post(
                            post_id,
                            'Twitter: Skipped because non-media posts are disabled or the media file was not found',
                            '',
                            ''
                        )

                # Post on Mastodon
                if MASTODON_INSTANCE_DOMAIN:

                    attachment = MediaAttachment(source_posts[post],
                                                 IMGUR_CLIENT,
                                                 IMGUR_CLIENT_SECRET,
                                                 IMAGE_DIR,
                                                 MediaAttachment.HIGH_RES,
                                                 logger
                                                 )

                    # Check for duplicate of attachment sha256
                    if duplicate_check(attachment.check_sum_high_res):
                        logger.info('Skipping %s because attachment with hash %s has already been posted' % (
                            post_id, attachment.check_sum_high_res))
                        attachment.destroy()
                        continue

                    # Make sure the post contains media,
                    # if MEDIA_POSTS_ONLY in config is set to True
                    if (((MEDIA_POSTS_ONLY is True) and attachment.media_path_high_res)
                            or (MEDIA_POSTS_ONLY is False)):
                        try:
                            NUM_NON_PROMO_MESSAGES += 1
                            # Generate post caption
                            caption = get_caption(source_posts[post], MAX_LEN_TOOT, addhashtags=additional_hashtags)
                            # Post the toot
                            if attachment.media_path_high_res:
                                logger.info('Posting this on Mastodon with media: %s' % caption)
                                logger.info('High Res Media checksum: %s' % attachment.check_sum_high_res)
                                media = mastodon.media_post(attachment.media_path_high_res, mime_type=None)
                                # If the post is marked as NSFW on Reddit,
                                # force sensitive media warning for images
                                if source_posts[post].over_18 and NSFW_POSTS_MARKED:
                                    toot = mastodon.status_post(caption, media_ids=[media], spoiler_text='NSFW')
                                else:
                                    toot = mastodon.status_post(
                                        caption,
                                        media_ids=[media],
                                        sensitive=MASTODON_SENSITIVE_MEDIA)

                            else:
                                logger.info('Posting this on Mastodon: %s' % caption)
                                # Add NSFW warning for Reddit posts marked as NSFW
                                if source_posts[post].over_18:
                                    toot = mastodon.status_post(caption, spoiler_text='NSFW')
                                else:
                                    toot = mastodon.status_post(caption)
                            # Log the toot
                            log_post(post_id, toot["url"], shared_url, attachment.check_sum_high_res)
                        except BaseException as e:
                            logger.error('Error while posting toot: %s' % e)
                            # Log the post anyways
                            log_post(post_id, 'Error while posting toot: %s' % e, '', '')

                    else:
                        logger.warning(
                            'Mastodon: Skipping %s because non-media posts are disabled or the media file was not found'
                            % post_id)
                        # Log the post anyways
                        log_post(
                            post_id,
                            'Mastodon: Skipped because non-media posts are disabled or the media file was not found',
                            '',
                            ''
                        )

                    # Clean up media file
                    attachment.destroy()

                # Return control to main loop
                break_to_mainloop = True
                break

            else:
                logger.info('Skipping %s because it was already posted' % post_id)


# Make sure config file exists
try:
    config = configparser.ConfigParser()
    config.read('config.ini')
except BaseException as e:
    print('[ERROR] Error while reading config file: %s' % e)
    sys.exit()
# General settings
CACHE_CSV = config['BotSettings']['CacheFile']
DELAY_BETWEEN_TWEETS = int(config['BotSettings']['DelayBetweenPosts'])
RUN_ONCE_ONLY = bool(
    distutils.util.strtobool(config['BotSettings']['RunOnceOnly']))
POST_LIMIT = int(config['BotSettings']['PostLimit'])
NSFW_POSTS_ALLOWED = bool(
    distutils.util.strtobool(config['BotSettings']['NSFWPostsAllowed']))
NSFW_POSTS_MARKED = bool(
    distutils.util.strtobool(config['BotSettings']['NSFWPostsMarked']))
SPOILERS_ALLOWED = bool(
    distutils.util.strtobool(config['BotSettings']['SpoilersAllowed']))
SELF_POSTS_ALLOWED = bool(
    distutils.util.strtobool(config['BotSettings']['SelfPostsAllowed']))
if config['BotSettings']['Hashtags']:
    # Parse list of hashtags
    HASHTAGS = config['BotSettings']['Hashtags']
    HASHTAGS = [x.strip() for x in HASHTAGS.split(',')]
else:
    HASHTAGS = ''
LOG_LEVEL = 'INFO'
if config['BotSettings']['LogLevel']:
    LOG_LEVEL = config['BotSettings']['LogLevel']
# Settings related to promotional messages
PROMO_EVERY = int(config['PromoSettings']['PromoEvery'])
PROMO_MESSAGE = config['PromoSettings']['PromoMessage']
# HealthChecks related settings
do_healthchecks = False
hc_base_url = config['HealthChecks']['BaseUrl']
hc_uid = config['HealthChecks']['UID']
if len(hc_base_url) > 0:
    do_healthchecks = True
# Settings related to media attachments
MEDIA_POSTS_ONLY = bool(
    distutils.util.strtobool(config['MediaSettings']['MediaPostsOnly']))
IMAGE_DIR = config['MediaSettings']['MediaFolder']
# Twitter info
POST_TO_TWITTER = bool(
    distutils.util.strtobool(config['Twitter']['PostToTwitter']))
# Mastodon info
MASTODON_INSTANCE_DOMAIN = config['Mastodon']['InstanceDomain']
MASTODON_SENSITIVE_MEDIA = bool(
    distutils.util.strtobool(config['Mastodon']['SensitiveMedia']))

SUBREDDITS = config.items('Subreddits')

# Set-up logging
logger = logging.getLogger(__name__)
coloredlogs.install(
    level=LOG_LEVEL,
    fmt='%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s',
    datefmt='%H:%M:%S')

# Check for updates
try:
    response = requests.get('https://gitlab.com/marvin8/tootbot/-/raw/master/update-check/current-version.txt')
    response.raise_for_status()
    new_version = response.content.decode('utf-8').strip()
    current_version = 2.09  # Current version of script
    if current_version < float(new_version):
        logger.warning('A new version of Tootbot (' + str(new_version) +
                       ') is available! (you have ' +
                       str(current_version) + ')')
        logger.warning(
            'Get the latest update from here: https://gitlab.com/marvin8/tootbot/'
        )
    else:
        logger.info('You have the latest version of Tootbot (' + str(current_version) + ')')
except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError) as re:
    logger.error('while checking for updates we got this error: %s' % re)

# Setup and verify Reddit access
if not os.path.exists('reddit.secret'):
    logger.warning('Reddit API keys not found. (See wiki if you need help).')
    # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
    REDDIT_AGENT = ''.join(input("[ .. ] Enter Reddit agent: ").split())
    REDDIT_CLIENT_SECRET = ''.join(
        input("[ .. ] Enter Reddit client secret: ").split())
    # Make sure authentication is working
    try:
        reddit_client = praw.Reddit(user_agent='Tootbot', client_id=REDDIT_AGENT, client_secret=REDDIT_CLIENT_SECRET)
        test = reddit_client.subreddit('announcements')
        # It worked, so save the keys to a file
        reddit_config = configparser.ConfigParser()
        reddit_config['Reddit'] = {'Agent': REDDIT_AGENT, 'ClientSecret': REDDIT_CLIENT_SECRET}
        with open('reddit.secret', 'w') as f:
            reddit_config.write(f)
        f.close()
    except BaseException as e:
        logger.error('Error while logging into Reddit: %s' % e)
        logger.error('Tootbot cannot continue, now shutting down')
        exit()
else:
    # Read API keys from secret file
    reddit_config = configparser.ConfigParser()
    reddit_config.read('reddit.secret')
    REDDIT_AGENT = reddit_config['Reddit']['Agent']
    REDDIT_CLIENT_SECRET = reddit_config['Reddit']['ClientSecret']
# Setup and verify Imgur access
if not os.path.exists('imgur.secret'):
    logger.warning(
        'Imgur API keys not found. (See wiki if you need help).'
    )
    # Whitespaces are stripped from input: https://stackoverflow.com/a/3739939
    IMGUR_CLIENT = ''.join(input("[ .. ] Enter Imgur client ID: ").split())
    IMGUR_CLIENT_SECRET = ''.join(input("[ .. ] Enter Imgur client secret: ").split())
    # Make sure authentication is working
    try:
        imgur_client = ImgurClient(IMGUR_CLIENT, IMGUR_CLIENT_SECRET)
        test_gallery = imgur_client.get_album('dqOyj')
        # It worked, so save the keys to a file
        imgur_config = configparser.ConfigParser()
        imgur_config['Imgur'] = {
            'ClientID': IMGUR_CLIENT,
            'ClientSecret': IMGUR_CLIENT_SECRET
        }
        with open('imgur.secret', 'w') as f:
            imgur_config.write(f)
        f.close()
    except BaseException as e:
        logger.error('Error while logging into Imgur: %s' % e)
        logger.error('Tootbot cannot continue, now shutting down')
        exit()
else:
    # Read API keys from secret file
    imgur_config = configparser.ConfigParser()
    imgur_config.read('imgur.secret')
    IMGUR_CLIENT = imgur_config['Imgur']['ClientID']
    IMGUR_CLIENT_SECRET = imgur_config['Imgur']['ClientSecret']
# Log into Twitter if enabled in settings
if POST_TO_TWITTER is True:
    if os.path.exists('twitter.secret'):
        # Read API keys from secret file
        twitter_config = configparser.ConfigParser()
        twitter_config.read('twitter.secret')
        ACCESS_TOKEN = twitter_config['Twitter']['AccessToken']
        ACCESS_TOKEN_SECRET = twitter_config['Twitter']['AccessTokenSecret']
        CONSUMER_KEY = twitter_config['Twitter']['ConsumerKey']
        CONSUMER_SECRET = twitter_config['Twitter']['ConsumerSecret']
        try:
            # Make sure authentication is working
            test_twitter_auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            test_twitter_auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
            twitter = tweepy.API(test_twitter_auth)
            twitter_username = twitter.me().screen_name
            logger.info('Successfully authenticated on Twitter as @' +
                        twitter_username)
        except BaseException as e:
            logger.error('Error while logging into Twitter: %s' % e)
            logger.error('Tootbot cannot continue, now shutting down')
            exit()
    else:
        # If the secret file doesn't exist, it means the setup process
        # hasn't happened yet
        logger.warning('Twitter API keys not found. (See wiki for help).')
        # Whitespaces are stripped from input:
        # https://stackoverflow.com/a/3739939
        ACCESS_TOKEN = ''.join(input('[ .. ] Enter access token for Twitter account: ').split())
        ACCESS_TOKEN_SECRET = ''.join(input('[ .. ] Enter access token secret for Twitter account: ').split())
        CONSUMER_KEY = ''.join(input('[ .. ] Enter consumer key for Twitter account: ').split())
        CONSUMER_SECRET = ''.join(input('[ .. ] Enter consumer secret for Twitter account: ').split())
        logger.info('Attempting to log in to Twitter...')
        try:
            # Make sure authentication is working
            test_twitter_auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            test_twitter_auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
            twitter = tweepy.API(test_twitter_auth)
            twitter_username = twitter.me().screen_name
            logger.info('Successfully authenticated on Twitter as @' +
                        twitter_username)
            # It worked, so save the keys to a file
            twitter_config = configparser.ConfigParser()
            twitter_config['Twitter'] = {
                'AccessToken': ACCESS_TOKEN,
                'AccessTokenSecret': ACCESS_TOKEN_SECRET,
                'ConsumerKey': CONSUMER_KEY,
                'ConsumerSecret': CONSUMER_SECRET
            }
            with open('twitter.secret', 'w') as f:
                twitter_config.write(f)
            f.close()
        except BaseException as e:
            logger.error('Error while logging into Twitter: %s' % e)
            logger.error('Tootbot cannot continue, now shutting down')
            exit()
# Log into Mastodon if enabled in settings
if MASTODON_INSTANCE_DOMAIN:
    if not os.path.exists('mastodon.secret'):
        # If the secret file doesn't exist,
        # it means the setup process hasn't happened yet
        logger.warning('Mastodon API keys not found. (See wiki for help).')
        MASTODON_USERNAME = input(
            "[ .. ] Enter email address for Mastodon account: ")
        MASTODON_PASSWORD = input(
            "[ .. ] Enter password for Mastodon account: ")
        logger.info('Generating login key for Mastodon...')
        try:
            Mastodon.create_app(
                'Tootbot',
                website='https://gitlab.com/marvin8/tootbot',
                api_base_url='https://' + MASTODON_INSTANCE_DOMAIN,
                to_file='mastodon.secret')
            mastodon = Mastodon(client_id='mastodon.secret',
                                api_base_url='https://' +
                                             MASTODON_INSTANCE_DOMAIN)
            mastodon.log_in(MASTODON_USERNAME,
                            MASTODON_PASSWORD,
                            to_file='mastodon.secret')
            # Make sure authentication is working
            mastodon_username = mastodon.account_verify_credentials()['username']
            logger.info(
                'Successfully authenticated on ' + MASTODON_INSTANCE_DOMAIN +
                ' as @' + mastodon_username +
                ', login information now stored in mastodon.secret file')
        except BaseException as e:
            logger.error('Error while logging into Mastodon: %s' % e)
            logger.error('Tootbot cannot continue, now shutting down')
            exit()
    else:
        try:
            mastodon = Mastodon(access_token='mastodon.secret',
                                api_base_url='https://' +
                                             MASTODON_INSTANCE_DOMAIN)
            # Make sure authentication is working
            username = mastodon.account_verify_credentials()['username']
            logger.info('Successfully authenticated on %s as @%s' % (MASTODON_INSTANCE_DOMAIN, username))
        except BaseException as e:
            logger.error('Error while logging into Mastodon: %s' % e)
            logger.error('Tootbot cannot continue, now shutting down')
            exit()
# Set the command line window title on Windows
if os.name == 'nt':
    try:
        if POST_TO_TWITTER and MASTODON_INSTANCE_DOMAIN:
            # Set title with both Twitter and Mastodon usernames
            # twitter_username = twitter.me().screen_name
            mastodon_username = mastodon.account_verify_credentials()['username']
            os.system('title ' + twitter_username + '@twitter.com and ' +
                      mastodon_username + '@' + MASTODON_INSTANCE_DOMAIN +
                      ' - Tootbot')
        elif POST_TO_TWITTER:
            # Set title with just Twitter username
            twitter_username = twitter.me().screen_name
            os.system('title ' + '@' + twitter_username + ' - Tootbot')
        elif MASTODON_INSTANCE_DOMAIN:
            # Set title with just Mastodon username
            mastodon_username = mastodon.account_verify_credentials()['username']
            os.system('title ' + mastodon_username + '@' +
                      MASTODON_INSTANCE_DOMAIN + ' - Tootbot')
    except:
        os.system('title Tootbot')

# Make sure logging file and media directory exists
if not os.path.exists(CACHE_CSV):
    with open(CACHE_CSV, 'w', newline='') as new_cache_file:
        default = ['Reddit post ID', 'Date and time', 'Post link', 'Media Checksum']
        wr = csv.writer(new_cache_file)
        wr.writerow(default)
    logger.info('%s file not found, created a new one' % CACHE_CSV)
    new_cache_file.close()

# Setup healthcheck monitoring
healthcheck = HealthChecks(base_url=hc_base_url,
                           uid=hc_uid,
                           logger=logger)

reddit = RedditHelper(REDDIT_AGENT, REDDIT_CLIENT_SECRET, logger=logger)

# Run the main script
NUM_NON_PROMO_MESSAGES = 0  # type: int
while True:
    if do_healthchecks:
        healthcheck.check_start()

    try:
        reddit_posts = {}
        for subreddit, hashtags in SUBREDDITS:
            reddit_posts[hashtags] = reddit.get_reddit_posts(subreddit,
                                                             NSFW_POSTS_ALLOWED,
                                                             SELF_POSTS_ALLOWED,
                                                             SPOILERS_ALLOWED)
        make_post(reddit_posts)
    except BaseException as e:
        logger.error('Error in main process: %s' % e)

    if do_healthchecks:
        healthcheck.check_ok()

    if RUN_ONCE_ONLY:
        logger.info('Exiting because RunOnceOnly is set to %s', RUN_ONCE_ONLY)
        sys.exit()

    logger.info('Sleeping for %s seconds' % DELAY_BETWEEN_TWEETS)
    time.sleep(DELAY_BETWEEN_TWEETS)
    logger.info('Restarting main process...')
