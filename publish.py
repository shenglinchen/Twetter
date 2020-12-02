"""
This module is a collection of classes and methods to perform the actual posting of content to
 Mastodon / Twitter
"""

import os
import sys
from typing import List

import arrow
from mastodon import Mastodon
from mastodon import MastodonError

from collect import LinkedMediaHelper
from collect import MediaAttachment
from collect import RedditHelper
from control import Configuration


class MastodonPublisher:
    """
    Ease the publishing of content to Mastodon
    """

    MAX_LEN_TOOT = 500

    def __init__(self, config: Configuration, secrets_file: str = 'mastodon.secret') -> None:
        self.logger = config.bot.logger
        self.media_only = config.media.media_only
        self.nsfw_marked = config.reddit.nsfw_marked
        self.mastodon_config = config.mastodon_config
        self.post_recorder = config.bot.post_recorder
        self.num_non_promo_posts = 0
        self.promo = config.promo

        api_base_url = 'https://' + self.mastodon_config.domain

        # Log into Mastodon if enabled in settings
        if not os.path.exists(secrets_file):
            # If the secret file doesn't exist,
            # it means the setup process hasn't happened yet
            self.logger.warning('Mastodon API keys not found. (See wiki for help).')
            user_name = input("[ .. ] Enter email address for Mastodon account: ")
            password = input("[ .. ] Enter password for Mastodon account: ")
            config.bot.logger.info('Generating login key for Mastodon...')
            try:
                Mastodon.create_app('Tootbot',
                                    website='https://gitlab.com/marvin8/tootbot',
                                    api_base_url=api_base_url,
                                    to_file=secrets_file)
                self.mastodon = Mastodon(client_id=secrets_file,
                                         api_base_url='https://' + self.mastodon_config.domain)
                self.mastodon.log_in(user_name, password, to_file=secrets_file)
                # Make sure authentication is working
                self.userinfo = self.mastodon.account_verify_credentials()
                mastodon_username = self.userinfo['username']
                config.bot.logger.info('Successfully authenticated on %s as @%s',
                                       self.mastodon_config.domain, mastodon_username)
                config.bot.logger.info('Mastodon login information now stored in %s file',
                                       secrets_file)
            except MastodonError as mastodon_error:
                config.bot.logger.error('Error while logging into Mastodon: %s', mastodon_error)
                config.bot.logger.error('Tootbot cannot continue, now shutting down')
                sys.exit(1)
        else:
            try:
                self.mastodon = Mastodon(access_token=secrets_file, api_base_url=api_base_url)
                # Make sure authentication is working
                self.userinfo = self.mastodon.account_verify_credentials()
                mastodon_username = self.userinfo['username']
                config.bot.logger.info('Successfully authenticated on %s as @%s',
                                       self.mastodon_config.domain,
                                       mastodon_username)
            except MastodonError as mastodon_error:
                config.bot.logger.error('Error while logging into Mastodon: %s', mastodon_error)
                config.bot.logger.error('Tootbot cannot continue, now shutting down')
                sys.exit(1)

    def make_post(self, posts: dict, reddit_helper: RedditHelper,
                  media_helper: LinkedMediaHelper) -> None:
        """
        Makes a post on mastodon from a selection of reddit submissions.

        Arguments:
            posts: A dictionary of subreddit specific hash tags and PRAW Submission objects
            reddit_helper: Helper class to work with Reddit
            media_helper: Helper class to retrieve media linked to from a reddit Submission.
        """
        break_to_mainloop = False
        for additional_hashtags, source_posts in posts.items():
            if break_to_mainloop:
                break

            for post in source_posts:
                # Grab post details from dictionary
                post_id = source_posts[post].id
                shared_url = source_posts[post].url
                if not (self.post_recorder.duplicate_check(post_id) or
                        self.post_recorder.duplicate_check(shared_url)):
                    self.logger.debug('Processing reddit post: %s', source_posts[post])

                    attachments = MediaAttachment(source_posts[post],
                                                  media_helper,
                                                  self.logger
                                                  )
                    number_attachments = len(attachments.media_paths)

                    self._remove_posted_earlier(attachments)

                    if number_attachments > 0 and len(attachments.media_paths) == 0:
                        self.logger.info(
                            'Skipping %s because all attachments have already been posted', post_id)
                        self.post_recorder.log_post(
                            post_id,
                            'Mastodon: Skipped because all images have already been posted',
                            '',
                            '')
                        continue

                    self.logger.debug('Media posts only: %s', self.media_only)
                    # Make sure the post contains media,
                    # if MEDIA_POSTS_ONLY in config is set to True
                    if (self.media_only and len(attachments.media_paths) > 0) or \
                            (not self.media_only):

                        self.logger.debug('Going to post Toot.')

                        try:
                            promo_message = None
                            if self.num_non_promo_posts >= self.promo.every > 0:
                                promo_message = self.promo.message
                                self.num_non_promo_posts = -1

                            # Generate post caption
                            caption = reddit_helper.get_caption(source_posts[post],
                                                                MastodonPublisher.MAX_LEN_TOOT,
                                                                add_hash_tags=additional_hashtags,
                                                                promo_message=promo_message)

                            # Upload media files if available
                            media_ids = None
                            if len(attachments.media_paths) > 0:
                                self.logger.info('Posting to Mastodon with media(s): %s', caption)
                                media_ids = self._post_attachments(attachments, post_id)
                            else:
                                self.logger.info('Posting to Mastodon without media: %s', caption)

                            spoiler = None
                            if source_posts[post].over_18 and self.nsfw_marked:
                                spoiler = 'NSFW'

                            toot = self.mastodon.status_post(
                                status=caption,
                                media_ids=media_ids,
                                sensitive=self.mastodon_config.media_always_sensitive,
                                spoiler_text=spoiler)

                            # Log the toot
                            self.post_recorder.log_post(post_id, toot["url"], shared_url, '')

                            self.num_non_promo_posts += 1
                            self.mastodon_config.number_of_errors = 0

                        except MastodonError as mastodon_error:
                            self.logger.error('Error while posting toot: %s', mastodon_error)
                            # Log the post anyways so we don't get into a loop of the same error
                            self.post_recorder.log_post(
                                post_id,
                                'Error while posting toot: %s' % mastodon_error,
                                '',
                                '')
                            self.mastodon_config.number_of_errors += 1

                    else:
                        self.logger.warning(
                            'Skipping %s, non-media posts disabled or media file not found',
                            post_id)
                        # Log the post anyways
                        self.post_recorder.log_post(
                            post_id,
                            'Skipping, non-media posts disabled or media file not found',
                            '',
                            ''
                        )

                    # Clean up media file
                    attachments.destroy()

                    # Return control to main loop
                    break_to_mainloop = True
                    break

                self.logger.info('Skipping %s because it was already posted', post_id)

    def _post_attachments(self, attachments: MediaAttachment, post_id: str) -> List[dict]:
        """
        _post_attachments post any media in attachments.media_paths list

        Arguments:
            attachments: object with a list of paths to media to be posted on Mastodon

        Returns:
            media_ids: List of dicts returned by mastodon.media_post
        """
        media_ids = []
        for checksum, media_path in attachments.media_paths.items():
            self.logger.info('Media %s with checksum: %s',
                             media_path,
                             checksum)
            media = self.mastodon.media_post(media_path)
            # Log the media upload
            self.post_recorder.log_post(post_id,
                                        '',
                                        media_path, checksum)
            media_ids.append(media)
        return media_ids

    def _remove_posted_earlier(self, attachments: MediaAttachment) -> None:
        """
        _remove_posted_earlier checks che checksum of all proposed attachments and removes any from
        the list that have already been posted earlier.

        Arguments:
            attachments: object with list of paths to media files proposed to be posted on Mastodon
        """
        # Build a list of checksums for files that have already been posted earlier
        checksums = []
        for checksum in attachments.media_paths:
            self.logger.debug('Media attachment (path, checksum): %s, %s',
                              attachments.media_paths[checksum], checksum)
            if attachments.media_paths[checksum] is None:
                checksums.append(checksum)
            # Check for duplicate of attachment sha256
            elif self.post_recorder.duplicate_check(checksum):
                self.logger.info('Media with checksum %s has already been posted',
                                 checksum)
                checksums.append(checksum)
        # Remove all empty or previously posted images
        for checksum in checksums:
            attachments.destroy_one_attachment(checksum)

    def delete_toots(self, older_than_days: int) -> None:
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
                toots = self.mastodon.account_statuses(self.userinfo['id'], max_id=max_id,
                                                       limit=10)

            # Actually deleting toots that are older than "older_than_days"
            for toot in toots:
                created_at = arrow.get(toot['created_at'])
                if created_at < oldest_to_keep:
                    self.logger.info('Deleting toot %s from %s', toot['url'], toot['created_at'])
                    self.mastodon.status_delete(toot['id'])
        except MastodonError as mastodon_error:
            self.logger.error('Encountered error while deleting_toots: %s ', mastodon_error)
