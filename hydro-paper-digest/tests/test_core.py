import json
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import core


def paper(lang):
    return {'id': 'https://openalex.org/' + lang, 'identity': 'doi:' + lang,
            'title': '홍수 flood', 'authors': ['A'], 'abstract': 'evidence',
            'published': '2026-11-01', 'citations': 10, 'lang': lang,
            'doi': None, 'pdf_url': 'https://example.org/a.pdf', 'journal': 'Test', 'score': 1}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = {**core.DEFAULTS, 'openalex_key': 'test', 'openai_key': 'test', 'download_pdf': False}
        self.day = date(2026, 11, 17)

    def tearDown(self):
        self.temp.cleanup()

    def test_kst_midnight(self):
        self.assertEqual(datetime(2026, 11, 16, 15, tzinfo=timezone.utc).astimezone(core.KST).date(), self.day)

    def test_abstract(self):
        self.assertEqual(core.abstract({'abstract_inverted_index': {'B': [1], 'A': [0]}}), 'A B')

    def test_rank(self):
        self.assertGreater(core.rank(paper('en'), self.day), core.rank({**paper('en'), 'published': '2026-01-01'}, self.day))

    def test_config_roundtrip(self):
        core.save_config(self.config, self.home)
        self.assertEqual(core.load_config(self.home), self.config)

    def test_notion_page_url(self):
        value = '0123456789abcdef0123456789abcdef'
        self.assertEqual(core.page_id('https://www.notion.so/Research-' + value + '?x=1'), value)
        with self.assertRaises(ValueError):
            core.page_id('not-a-page')

    def test_lock_releases(self):
        with core.single_run(self.home):
            with self.assertRaises(RuntimeError):
                with core.single_run(self.home):
                    pass
        with core.single_run(self.home):
            pass

    @patch.object(core, 'search', side_effect=lambda config, lang, day: [paper(lang)])
    @patch.object(core, 'summarize', return_value={'reason': '동기', 'summary': ['1', '2', '3']})
    def test_daily_and_crossday_duplicate(self, summarize, search):
        for day in [self.day, self.day, date(2026, 11, 18)]:
            core.run(self.config, self.home, day, lambda x: None)
        c = core.connect(self.home)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM papers').fetchone()[0], 2)
        c.close()
        self.assertEqual(summarize.call_count, 2)
        self.assertTrue((self.home / str(self.day) / 'ko.md').exists())

    @patch.object(core, 'search', side_effect=lambda config, lang, day: [paper(lang)] if lang == 'en' else [])
    @patch.object(core, 'summarize', return_value={'reason': '동기', 'summary': ['1', '2', '3']})
    def test_language_shortage(self, *mocks):
        messages = []
        core.run(self.config, self.home, self.day, messages.append)
        self.assertTrue(any('새 논문 없음' in m for m in messages))
        c = core.connect(self.home)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM papers').fetchone()[0], 1)
        c.close()

    @patch.object(core, 'database', return_value=('database', {}))
    @patch.object(core, 'sync', side_effect=[RuntimeError('test'), 'ok1', 'ok2'])
    @patch.object(core, 'search', side_effect=lambda config, lang, day: [paper(lang)])
    @patch.object(core, 'summarize', return_value={'reason': '동기', 'summary': ['1', '2', '3']})
    def test_pending_notion_retry(self, *mocks):
        self.config.update(notion_token='test', notion_page='test')
        core.run(self.config, self.home, self.day, lambda x: None)
        core.run(self.config, self.home, self.day, lambda x: None)
        c = core.connect(self.home)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM papers WHERE notion_id IS NULL').fetchone()[0], 0)
        c.close()

    @patch.object(core, 'api', return_value={'choices': [{'message': {'content': '{"reason":"x","summary":["only"]}'}}]})
    def test_invalid_summary(self, api):
        with self.assertRaises(ValueError):
            core.summarize(self.config, paper('en'))

    @patch.object(core, 'api')
    def test_database_schema(self, api):
        self.config.update(notion_token='test', notion_page='0' * 32)
        api.side_effect = [{'results': [], 'has_more': False}, {'id': 'db'}]
        self.assertEqual(core.database(self.config)[0], 'db')
        schema = api.call_args.kwargs['payload']['properties']
        self.assertIn('3줄 요약', schema)
        self.assertIn('논문 ID', schema)

    @patch.object(core, 'api')
    def test_database_reuse(self, api):
        self.config.update(notion_token='test', notion_page='0' * 32)
        api.return_value = {'results': [{'id': 'db', 'type': 'child_database', 'child_database': {'title': core.DB_TITLE}}], 'has_more': False}
        self.assertEqual(core.database(self.config)[0], 'db')
        self.assertEqual(api.call_count, 1)

    @patch.object(core, 'api')
    def test_notion_row_columns_and_recover(self, api):
        p = {**paper('ko'), 'day': str(self.day), 'reason': '동기', 'summary': ['1', '2', '3']}
        api.side_effect = [{'results': []}, {'id': 'row'}]
        self.assertEqual(core.sync(p, 'db', {}), 'row')
        body = api.call_args.kwargs['payload']
        self.assertEqual(body['parent'], {'database_id': 'db'})
        self.assertEqual(body['properties']['3줄 요약']['rich_text'][0]['text']['content'], '1\n2\n3')
        api.reset_mock()
        api.side_effect = None
        api.return_value = {'results': [{'id': 'existing'}]}
        self.assertEqual(core.sync(p, 'db', {}), 'existing')
        self.assertEqual(api.call_count, 1)

    @patch.object(core, 'urlopen')
    def test_non_pdf_not_saved(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'<html>paywall</html>'
        self.assertIsNone(core.download(paper('en'), self.home))
        self.assertEqual(list(self.home.iterdir()), [])

    @patch.object(core, 'api')
    def test_search_deduplicates_and_filters(self, api):
        work = {'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1/test',
                'display_name': '홍수 예측 flood', 'abstract_inverted_index': {'홍수': [0], 'forecast': [1]},
                'best_oa_location': {'is_oa': True, 'pdf_url': 'https://example.org/a.pdf'},
                'publication_date': '2026-11-01', 'cited_by_count': 5}
        api.return_value = {'results': [work, work, {**work, 'id': 'no-abstract', 'abstract_inverted_index': None}]}
        rows = core.search(self.config, 'ko', self.day)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], '홍수 예측 flood')


if __name__ == '__main__':
    unittest.main()
