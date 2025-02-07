from django.contrib import admin
from django.contrib.sites.models import Site
from django.test import RequestFactory

from cms.extensions.extension_pool import ExtensionPool
from cms.models import PageContent
from cms.test_utils.testcases import CMSTestCase
from cms.toolbar.toolbar import CMSToolbar
from cms.utils.urlutils import admin_reverse

from djangocms_versioning.cms_config import copy_page_content
from djangocms_versioning.models import Version
from djangocms_versioning.plugin_rendering import VersionContentRenderer
from djangocms_versioning.test_utils.extended_polls.admin import PollExtensionAdmin
from djangocms_versioning.test_utils.extended_polls.models import PollTitleExtension
from djangocms_versioning.test_utils.extensions.models import (
    TestPageExtension,
    TestTitleExtension,
)
from djangocms_versioning.test_utils.factories import (
    PageContentFactory,
    PageFactory,
    PageVersionFactory,
    PlaceholderFactory,
    PollTitleExtensionFactory,
    PollVersionFactory,
    TestTitleExtensionFactory,
    TextPluginFactory,
)


class MonkeypatchExtensionTestCase(CMSTestCase):
    def setUp(self):
        self.version = PageVersionFactory(content__language="en")
        de_pagecontent = PageContentFactory(
            page=self.version.content.page, language="de"
        )
        self.page = self.version.content.page
        site = Site.objects.first()
        self.new_page = self.page.copy(
            site=site,
            parent_node=self.page.node.parent,
            translations=False,
            permissions=False,
            extensions=False,
        )
        new_page_content = PageContentFactory(page=self.new_page, language='de')
        self.new_page.title_cache[de_pagecontent.language] = new_page_content

    def test_copy_extensions(self):
        """Try to copy the extension, without the monkeypatch this tests fails"""
        extension_pool = ExtensionPool()
        extension_pool.page_extensions = set([TestPageExtension])
        extension_pool.title_extensions = set([TestTitleExtension])
        extension_pool.copy_extensions(
            self.page, self.new_page, languages=['de']
        )
        # No asserts, this test originally failed because the versioned manager was called
        # in copy_extensions, now we call the original manager instead
        # https://github.com/divio/djangocms-versioning/pull/201/files#diff-fc33dd7b5aa9b1645545cf48dfc9b4ecR19

    def test_pagecontent_copy_method_creates_extension_title_extension_attached(self):
        """
        The page content copy method should create a new title extension, if one is attached to it.
        """
        page_content = self.version.content
        poll_extension = PollTitleExtensionFactory(extended_object=page_content)
        poll_extension.votes = 5

        new_pagecontent = copy_page_content(page_content)

        self.assertNotEqual(new_pagecontent.polltitleextension, poll_extension)
        self.assertEqual(page_content.polltitleextension.pk, poll_extension.pk)
        self.assertNotEqual(page_content.polltitleextension.pk, new_pagecontent.polltitleextension.pk)
        self.assertEqual(new_pagecontent.polltitleextension.votes, 5)
        self.assertEqual(PollTitleExtension._base_manager.count(), 2)

    def test_pagecontent_copy_method_not_created_extension_title_extension_attached(self):
        """
        The pagecontent copy method should not create a new title extension, if one isn't attached to the pagecontent
        being copied
        """
        new_pagecontent = copy_page_content(self.version.content)

        self.assertFalse(hasattr(new_pagecontent, "polltitleextension"))
        self.assertEqual(PollTitleExtension._base_manager.count(), 0)

    def test_pagecontent_copy_method_creates_extension_multiple_title_extension_attached(self):
        """
        The page content copy method should handle creation of multiple extensions
        """
        page_content = self.version.content
        poll_extension = PollTitleExtensionFactory(extended_object=page_content)
        poll_extension.votes = 5
        title_extension = TestTitleExtensionFactory(extended_object=page_content)

        new_pagecontent = copy_page_content(page_content)

        self.assertNotEqual(new_pagecontent.polltitleextension, poll_extension)
        self.assertEqual(page_content.polltitleextension.pk, poll_extension.pk)
        self.assertNotEqual(new_pagecontent.testtitleextension, poll_extension)
        self.assertEqual(page_content.testtitleextension.pk, poll_extension.pk)
        self.assertNotEqual(new_pagecontent.polltitleextension, poll_extension)
        self.assertNotEqual(new_pagecontent.testtitleextension, title_extension)
        self.assertEqual(new_pagecontent.polltitleextension.votes, 5)
        self.assertEqual(PollTitleExtension._base_manager.count(), 2)
        self.assertEqual(TestTitleExtension._base_manager.count(), 2)

    def test_title_extension_admin_monkey_patch_save(self):
        """
        When hitting the monkeypatched save method, with a draft pagecontent, ensure that we don't see failures
        due to versioning overriding monkeypatches
        """
        poll_extension = PollTitleExtensionFactory(extended_object=self.version.content)
        model_site = PollExtensionAdmin(admin_site=admin.AdminSite(), model=PollTitleExtension)
        test_url = admin_reverse("extended_polls_polltitleextension_change", args=(poll_extension.pk,))
        test_url += "?extended_object=%s" % self.version.content.pk
        request = RequestFactory().post(path=test_url)
        request.user = self.get_superuser()

        poll_extension.votes = 1
        model_site.save_model(request, poll_extension, form=None, change=False)

        self.assertEqual(PollTitleExtension.objects.first().votes, 1)
        self.assertEqual(PollTitleExtension.objects.count(), 1)

    def test_title_extension_admin_monkey_patch_save_date_modified_updated(self):
        """
        When making changes to an extended model that is attached to a PageContent via
        the Title Extension the date modified in a version should also be updated to reflect
        the correct date timestamp.
        """
        poll_extension = PollTitleExtensionFactory(extended_object=self.version.content)
        model_site = PollExtensionAdmin(admin_site=admin.AdminSite(), model=PollTitleExtension)
        pre_changes_date_modified = Version.objects.get(id=self.version.pk).modified
        test_url = admin_reverse("extended_polls_polltitleextension_change", args=(poll_extension.pk,))
        test_url += "?extended_object=%s" % self.version.content.pk

        request = RequestFactory().post(path=test_url)
        request.user = self.get_superuser()
        model_site.save_model(request, poll_extension, form=None, change=False)

        post_changes_date_modified = Version.objects.get(id=self.version.pk).modified

        self.assertNotEqual(pre_changes_date_modified, post_changes_date_modified)

    def test_title_extension_admin_monkeypatch_add_view(self):
        """
        When hitting the add view, without the monkeypatch, the pagecontent queryset will be filtered to only show
        published. Hit it with a draft, to make sure the monkeypatch works.
        """
        with self.login_user_context(self.get_superuser()):
            response = self.client.get(
                admin_reverse("extended_polls_polltitleextension_add") +
                "?extended_object=%s" % self.version.content.pk,
                follow=True
            )
            self.assertEqual(response.status_code, 200)


class MonkeypatchTestCase(CMSTestCase):
    def test_content_renderer(self):
        """Test that cms.toolbar.toolbar.CMSToolbar.content_renderer
        is replaced with a property returning VersionContentRenderer
        """
        request = self.get_request("/")
        self.assertEqual(
            CMSToolbar(request).content_renderer.__class__, VersionContentRenderer
        )

    def test_get_admin_model_object(self):
        """
        PageContent normally won't be able to fetch objects in draft.
        With the mocked get_admin_model_object_by_id it is able to fetch objects
        in draft mode.
        """
        from cms.utils.helpers import get_admin_model_object_by_id

        version = PageVersionFactory()
        content = get_admin_model_object_by_id(PageContent, version.content.pk)

        self.assertEqual(version.state, 'draft')
        self.assertEqual(content.pk, version.content.pk)

    def test_success_url_for_cms_wizard(self):
        from cms.cms_wizards import cms_page_wizard, cms_subpage_wizard
        from cms.toolbar.utils import get_object_preview_url

        from djangocms_versioning.test_utils.polls.cms_wizards import poll_wizard

        # Test against page creations in different languages.
        version = PageVersionFactory(content__language="en")
        self.assertEqual(
            cms_page_wizard.get_success_url(version.content.page, language="en"),
            get_object_preview_url(version.content),
        )

        version = PageVersionFactory(content__language="en")
        self.assertEqual(
            cms_subpage_wizard.get_success_url(version.content.page, language="en"),
            get_object_preview_url(version.content),
        )

        version = PageVersionFactory(content__language="de")
        self.assertEqual(
            cms_page_wizard.get_success_url(version.content.page, language="de"),
            get_object_preview_url(version.content, language="de"),
        )

        # Test against a model that doesn't have a PlaceholderRelationField
        version = PollVersionFactory()
        self.assertEqual(
            poll_wizard.get_success_url(version.content),
            version.content.get_absolute_url(),
        )

    def test_get_title_cache(self):
        """Check that patched Page._get_title_cache fills
        the title_cache with _prefetched_objects_cache data.
        """
        version = PageVersionFactory(content__language="en")
        page = version.content.page
        page._prefetched_objects_cache = {"pagecontent_set": [version.content]}

        page._get_title_cache(language="en", fallback=False, force_reload=False)
        self.assertEqual({"en": version.content}, page.title_cache)


class MonkeypatchAdminTestCase(CMSTestCase):

    def test_default_cms_page_changelist_view_language_with_multi_language_content(self):
        """A multi lingual page shows the correct values when
        language filters / additional grouping values are set
        using the default CMS PageContent view
        """
        page = PageFactory(node__depth=1)
        en_version1 = PageVersionFactory(
            content__page=page,
            content__language="en",
        )
        fr_version1 = PageVersionFactory(
            content__page=page,
            content__language="fr",
        )

        # Use the tree endpoint which is what the pagecontent changelist depends on
        changelist_url = admin_reverse("cms_pagecontent_get_tree")
        with self.login_user_context(self.get_superuser()):
            en_response = self.client.get(changelist_url, {"language": "en"})
            fr_response = self.client.get(changelist_url, {"language": "fr"})

        # English values are only returned
        self.assertEqual(200, en_response.status_code)
        self.assertContains(en_response, en_version1.content.title)
        self.assertNotContains(en_response, fr_version1.content.title)

        # French values are only returned
        self.assertEqual(200, fr_response.status_code)
        self.assertContains(fr_response, fr_version1.content.title)
        self.assertNotContains(fr_response, en_version1.content.title)


class MonkeypatchPageAdminCopyLanguageTestCase(CMSTestCase):

    def setUp(self):
        self.user = self.get_superuser()
        page = PageFactory()
        self.source_version = PageVersionFactory(content__page=page, content__language="en")
        self.target_version = PageVersionFactory(content__page=page, content__language="it")
        # Add default placeholders
        source_placeholder = PlaceholderFactory(source=self.source_version.content, slot="content")
        self.source_version.content.placeholders.add(source_placeholder)
        target_placeholder = PlaceholderFactory(source=self.target_version.content, slot="content")
        self.target_version.content.placeholders.add(target_placeholder)
        # Populate only the source placeholder as this is what we will be copying!
        TextPluginFactory(placeholder=source_placeholder)

        # Use the endpoint that the toolbar copy uses, this indirectly runs the monkey patched logic!
        # Simulating the user selecting in the Language menu "Copy all plugins" in the Versioned Page toolbar
        self.copy_url = admin_reverse('cms_pagecontent_copy_language', args=(self.source_version.content.pk,))
        self.copy_url_data = {
            'source_language': "en",
            'target_language': "it"
        }

    def test_page_copy_language_copies_source_draft_placeholder_plugins(self):
        """
        A draft pages contents are copied to a different language
        """
        with self.login_user_context(self.user):
            response = self.client.post(self.copy_url, self.copy_url_data)

        self.assertEqual(response.status_code, 200)

        original_plugins = self.source_version.content.placeholders.get().cmsplugin_set.all()
        new_plugins = self.target_version.content.placeholders.get().cmsplugin_set.all()

        self.assertEqual(new_plugins.count(), 1)
        self.assertNotEqual(new_plugins[0].pk, original_plugins[0].pk)
        self.assertNotEqual(new_plugins[0].language, original_plugins[0].language)
        self.assertEqual(new_plugins[0].language, "it")
        self.assertEqual(new_plugins[0].position, original_plugins[0].position)
        self.assertEqual(new_plugins[0].plugin_type, original_plugins[0].plugin_type)
        self.assertEqual(
            new_plugins[0].djangocms_text_ckeditor_text.body,
            original_plugins[0].djangocms_text_ckeditor_text.body,
        )

    def test_copy_language_copies_source_published_placeholder_plugins(self):
        """
        A published pages contents are copied to a different language
        """
        # Publish the source version
        self.source_version.publish(self.user)

        with self.login_user_context(self.user):
            response = self.client.post(self.copy_url, self.copy_url_data)

        self.assertEqual(response.status_code, 200)

        original_plugins = self.source_version.content.placeholders.get().cmsplugin_set.all()
        new_plugins = self.target_version.content.placeholders.get().cmsplugin_set.all()

        self.assertEqual(new_plugins.count(), 1)
        self.assertNotEqual(new_plugins[0].pk, original_plugins[0].pk)
        self.assertNotEqual(new_plugins[0].language, original_plugins[0].language)
        self.assertEqual(new_plugins[0].language, "it")
        self.assertEqual(new_plugins[0].position, original_plugins[0].position)
        self.assertEqual(new_plugins[0].plugin_type, original_plugins[0].plugin_type)
        self.assertEqual(
            new_plugins[0].djangocms_text_ckeditor_text.body,
            original_plugins[0].djangocms_text_ckeditor_text.body,
        )

    def test_copy_language_cannot_copy_to_published_version(self):
        """
        A pages contents cannot be copied to a published target version!
        """
        # Publish the target version
        self.target_version.publish(self.user)

        with self.login_user_context(self.user):
            response = self.client.post(self.copy_url, self.copy_url_data)

        # the Target version should be protected and we should not be allowed to copy any plugins to it!
        self.assertEqual(response.status_code, 403)

    def test_copy_language_copies_from_page_with_different_placeholders(self):
        """
        PageContents stores the template, this means that each PageContent can have
        a different template and placeholders. We should only copy plugins from common placeholders.

        This test contains different templates and a partially populated source and target placeholders.
        All plugins in the source should be left unnafected
        """
        source_placeholder_1 = PlaceholderFactory(source=self.source_version.content, slot="source_placeholder_1")
        self.source_version.content.placeholders.add(source_placeholder_1)
        TextPluginFactory(placeholder=source_placeholder_1)
        target_placeholder_1 = PlaceholderFactory(source=self.target_version.content, slot="target_placeholder_1")
        self.target_version.content.placeholders.add(target_placeholder_1)
        TextPluginFactory(placeholder=target_placeholder_1)

        self.source_version.publish(self.user)

        with self.login_user_context(self.user):
            response = self.client.post(self.copy_url, self.copy_url_data)

        self.assertEqual(response.status_code, 200)

        source_placeholder_different = self.source_version.content.placeholders.get(
            slot="source_placeholder_1").cmsplugin_set.all()
        target_placeholder_different = self.target_version.content.placeholders.get(
            slot="target_placeholder_1").cmsplugin_set.all()

        self.assertEqual(source_placeholder_different.count(), 1)
        self.assertEqual(target_placeholder_different.count(), 1)
        self.assertNotEqual(
            source_placeholder_different[0].djangocms_text_ckeditor_text.body,
            target_placeholder_different[0].djangocms_text_ckeditor_text.body
        )
