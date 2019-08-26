"""Quick hack to determine HD mp4 download link for a gfycat video."""

from bs4 import BeautifulSoup
import requests


def get_gfycat_mp4_download_url(media_url):
    """Actual hack method."""
    response = requests.get(media_url)
    soup = BeautifulSoup(response.text, 'lxml')
    mp4_url = ""
    for tag in soup.find_all("source", src=True):
        src = tag['src']
        if "giant" in src:
            if "mp4" in src:
                mp4_url = src

    return mp4_url
