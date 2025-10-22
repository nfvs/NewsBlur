"""
End-to-end test for newsletter email processing.
"""

import json
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.newsletters.example_mailgun_email import params as mailgun_example_params
from apps.profile.models import Profile
from apps.reader.models import UserSubscriptionFolders
from apps.rss_feeds.models import Feed, MStory


class Test_NewsletterEndToEnd(TestCase):
    """End-to-end test for newsletter email processing."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="user", email="user@example.com")
        # Profile is auto-created by post_save signal, just retrieve it
        self.profile = Profile.objects.get(user=self.user)
        self.profile.secret_token = "test-token-123"
        self.profile.save()
        UserSubscriptionFolders.objects.create(user=self.user, folders="[]")

    def tearDown(self):
        """Clean up test data."""
        MStory.objects.all().delete()
        Feed.objects.all().delete()
        UserSubscriptionFolders.objects.all().delete()
        Profile.objects.all().delete()
        User.objects.all().delete()

    @patch("apps.rss_feeds.models.MStory.sync_feed_redis")
    @patch("apps.search.models.SearchFeed.generate_combined_feed_content_vector")
    @patch("apps.rss_feeds.models.redis.Redis")
    @patch("apps.newsletters.models.redis.Redis")
    def test_mailgun_webhook_creates_story_with_correct_html(
        self, mock_redis_newsletters, mock_redis_feeds, mock_search, mock_sync_redis
    ):
        """
        End-to-end test: Mailgun webhook -> story created with correct content.

        This test verifies the complete flow:
        1. Mailgun sends a POST webhook with newsletter email data
        2. Newsletter parsing extracts user, sender, subject, and HTML content
        3. Feed is created/retrieved for the newsletter sender
        4. Story is created and stored in the database
        """
        # Mock external dependencies
        mock_redis_instance = Mock()
        mock_redis_instance.zscore.return_value = 0
        mock_redis_instance.publish.return_value = 0
        mock_redis_newsletters.return_value = mock_redis_instance
        mock_redis_feeds.return_value = mock_redis_instance
        mock_search.return_value = None  # Bypass OpenAI embeddings
        mock_sync_redis.return_value = None  # Bypass Redis sync

        # Use the example email data as-is
        test_params = mailgun_example_params.copy()
        test_params["signature"] = "test-signature-123"  # Required field for story hash

        # Simulate Mailgun webhook POST request
        url = reverse("newsletter-receive")
        response = self.client.post(url, data=test_params)

        # Verify webhook accepted
        self.assertEqual(response.status_code, 200)

        # Verify story was created
        stories = MStory.objects.filter(story_title__contains="Test Newsletter")
        self.assertEqual(stories.count(), 1, "Exactly one story should be created")

        story = stories.first()

        # Verify feed was created with correct properties
        feed = Feed.objects.get(id=story.story_feed_id)
        self.assertTrue(feed.is_newsletter, "Feed should be marked as newsletter")
        self.assertIn("newsletter:", feed.feed_address, "Feed address should contain 'newsletter:'")
        self.assertIn("Test mailer", feed.feed_title, "Feed title should contain sender name")

        # Verify story metadata
        self.assertIn("Test mailer", story.story_author_name, "Author should be the sender")
