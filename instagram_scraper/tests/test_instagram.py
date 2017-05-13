import unittest
import os
import shutil
import tempfile
import requests_mock
import glob
from instagram_scraper import InstagramScraper
from instagram_scraper.constants import *

class InstagramTests(unittest.TestCase):

    def setUp(self):
        fixtures_path = os.path.join(os.path.dirname(__file__), 'fixtures')

        fixture_files = glob.glob(os.path.join(fixtures_path, '*'))

        for file_path in fixture_files:
            basename = os.path.splitext(os.path.basename(file_path))[0]
            self.__dict__[basename] = open(file_path).read()

        # This is a max id of the last item in response_first_page.json.
        self.max_id = "1369793132326237681_50955533"

        self.test_dir = tempfile.mkdtemp()

        args = {
            'usernames': ['test'],
            'destination': self.test_dir,
            'login_user': None,
            'login_pass': None,
            'quiet': True,
            'maximum': 0,
            'retain_username': False,
            'media_metadata': False,
            'media_types': ['image', 'video', 'story'],
            'latest': False
        }

        self.scraper = InstagramScraper(**args)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_scrape(self):
        with requests_mock.Mocker() as m:
            m.get(BASE_URL + self.scraper.usernames[0], text=self.response_user_metadata)
            m.get(MEDIA_URL.format(self.scraper.usernames[0]), text=self.response_first_page)
            m.get(MEDIA_URL.format(self.scraper.usernames[0]) + '?max_id=' + self.max_id,
                  text=self.response_second_page)
            m.get('https://fake-url.com/photo1.jpg', text="image1")
            m.get('https://fake-url.com/photo2.jpg', text="image2")
            m.get('https://fake-url.com/photo3.jpg', text="image3")

            self.scraper.scrape()

            # First page has photo1 and photo2, while second page has photo3. If photo3
            # is opened, generator successfully traversed both pages.
            self.assertEqual(open(os.path.join(self.test_dir, 'photo3.jpg')).read(),
                             "image3")

    def test_scrape_hashtag(self):
        with requests_mock.Mocker() as m:
            m.get(TAGS_URL.format('test'), text=self.response_explore_tags, cookies={'csrftoken': 'token'})
            m.post(QUERY_URL, [
                {'text': self.response_query_hashtag_first_page, 'status_code': 200},
                {'text': self.response_query_hashtag_second_page, 'status_code': 200}
            ])
            m.get(VIEW_MEDIA_URL.format('code4'), text=self.response_view_media_video)
            m.get('https://fake-url.com/video.mp4', text="video")

            self.scraper.scrape_hashtag()

            self.assertEqual(open(os.path.join(self.test_dir, 'video.mp4')).read(),
                             "video")

    def test_scrape_location(self):
        with requests_mock.Mocker() as m:
            m.get(LOCATIONS_URL.format('test'), text=self.response_explore_location, cookies={'csrftoken': 'token'})
            m.post(QUERY_URL, [
                {'text': self.response_query_hashtag_first_page, 'status_code': 200},
                {'text': self.response_query_hashtag_second_page, 'status_code': 200}
            ])
            m.get(VIEW_MEDIA_URL.format('code4'), text=self.response_view_media_video)
            m.get('https://fake-url.com/video.mp4', text="video")

            self.scraper.scrape_location()

            self.assertEqual(open(os.path.join(self.test_dir, 'video.mp4')).read(),
                             "video")
