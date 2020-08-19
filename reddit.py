import praw


class RedditHelper:

    def __init__(self, client_id, client_secret, user_agent='Tootbot', logger=None):
        self.logger = logger
        self.reddit_connection = praw.Reddit(user_agent=user_agent, client_id=client_id, client_secret=client_secret)

    def get_reddit_posts(self, subreddit, allow_nsfw, allow_self, allow_spoilers, limit=10):
        posts = {}
        if self.logger is not None:
            self.logger.info('Getting posts from Subreddit: "%s"' % subreddit)
        subreddit_info = self.reddit_connection.subreddit(subreddit)
        for submission in subreddit_info.hot(limit=limit):
            if submission.over_18 and allow_nsfw is False:
                # Skip over NSFW posts if they are disabled in the config file
                if self.logger is not None:
                    self.logger.info('Skipping %s because it is marked as NSFW' % submission.id)
                continue
            elif submission.is_self and allow_self is False:
                # Skip over NSFW posts if they are disabled in the config file
                if self.logger is not None:
                    self.logger.info('Skipping %s because it is a self post' % submission.id)
                continue
            elif submission.spoiler and allow_spoilers is False:
                # Skip over posts marked as spoilers if they are disabled in
                # the config file
                if self.logger is not None:
                    self.logger.info('Skipping %s because it is marked as a spoiler' % submission.id)
                continue
            elif submission.stickied:
                if self.logger is not None:
                    self.logger.info('Skipping %s because it is stickied' % submission.id)
                continue
            else:
                # Create dict
                posts[submission.id] = submission
        return posts
