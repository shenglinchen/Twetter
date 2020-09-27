# Tootbot

This is a Python bot that looks up posts from specified subreddits and automatically posts them on Twitter and/or [Mastodon](https://joinmastodon.org/). It is based on [reddit-twitter-bot](https://github.com/rhiever/reddit-twitter-bot). Tootbot is now used by [a wide variety of social media accounts](https://github.com/corbindavenport/tootbot/wiki/Accounts-using-Tootbot).

---

**!!! Please be aware that the current version of tootbot from this repo has bugs in the posting to Twitter code.  !!!** 

I am working on acquiring a Twitter developer account and fixing issues around posting to Twitter. You can follow [Issue 3](https://gitlab.com/marvin8/tootbot/-/issues/3) in this repo for progress.

---

**Features:**

* Tootbot can post to both Twitter and [Mastodon](https://joinmastodon.org/)
* Media from direct links, Gfycat, Imgur, Reddit, and Giphy is automatically attached in the social media post
* Links that do not contain media can be skipped, ideal for meme accounts like [@badreactiongifs](https://twitter.com/badreactiongifs)
* NSFW content, spoilers, and self-posts can be filtered
* Tootbot can monitor multiple subreddits at once
* Tootbot is fully open-source, so you don't have to give an external service full access to your social media accounts
* Tootbot also checks the sha256 checksum of media files to stop posting of the same media file from different subreddits.
* Tootbot can ping a [Healthchecks](https://healthchecks.io/) instance for monitoring continuous operation of Tootbot

Tootbot uses the 
[tweepy](https://github.com/tweepy/tweepy), 
[PRAW](https://praw.readthedocs.io/en/latest/), 
[py-gfycat](https://github.com/ankeshanand/py-gfycat),
[imgurpython](https://github.com/Imgur/imgurpython), 
[Pillow](https://github.com/python-pillow/Pillow), 
[coloredlogs](https://coloredlogs.readthedocs.io/en/latest/),
[requests](https://github.com/psf/requests),
[beautifulsoup4](http://www.crummy.com/software/BeautifulSoup/bs4/),
and [Mastodon.py](https://github.com/halcy/Mastodon.py) libraries. 

## Disclaimer

The developers of Tootbot hold no liability for what you do with this script or what happens to you by using this script. Abusing this script *can* get you banned from Twitter and/or Mastodon, so make sure to read up on proper usage of the API for each site.

## Setup and usage

For instructions on setting up and using Tootbot, please visit [the wiki](https://gitlab.com/marvin8/tootbot/-/wikis/home)

## Support this project

You can now support my work on this project by [buying me a coffee](https://www.buymeacoffee.com/marvin8).
