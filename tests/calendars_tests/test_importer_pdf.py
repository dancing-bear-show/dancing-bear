"""Tests for calendars/importer/pdf_parser.py."""

import unittest
from unittest.mock import patch, MagicMock
import datetime

from calendars.importer.pdf_parser import PDFParser, parse_pdf
from calendars.importer.model import ScheduleItem


class TestParsePdfBackwardCompat(unittest.TestCase):
    """Tests for parse_pdf backward compatibility function."""

    @patch.object(PDFParser, 'parse')
    def test_parse_pdf_delegates_to_parser(self, mock_parse):
        """Test parse_pdf() delegates to PDFParser.parse()."""
        mock_parse.return_value = [ScheduleItem(subject='Test')]
        result = parse_pdf('/path/to/file.pdf')
        mock_parse.assert_called_once_with('/path/to/file.pdf')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].subject, 'Test')


class TestPDFParserPdfminerMissing(unittest.TestCase):
    """Tests for PDFParser when pdfminer.six is not installed."""

    def test_parse_raises_when_pdfminer_missing(self):
        """Test parse() raises RuntimeError when pdfminer.six not installed."""
        parser = PDFParser()
        with patch.dict('sys.modules', {'pdfminer': None, 'pdfminer.high_level': None}):
            # Force import to fail
            with patch('builtins.__import__', side_effect=ImportError('No module named pdfminer')):
                with self.assertRaises(RuntimeError) as ctx:
                    parser.parse('/fake/path.pdf')
                self.assertIn('pdfminer.six is required', str(ctx.exception))


class TestPDFParserTryPdfplumber(unittest.TestCase):
    """Tests for PDFParser._try_pdfplumber()."""

    def test_try_pdfplumber_returns_empty_when_not_installed(self):
        """Test _try_pdfplumber returns empty list when pdfplumber not available."""
        parser = PDFParser()
        with patch.dict('sys.modules', {'pdfplumber': None}):
            with patch('builtins.__import__', side_effect=ImportError('No module named pdfplumber')):
                result = parser._try_pdfplumber('/fake/path.pdf')
                self.assertEqual(result, [])

    def test_try_pdfplumber_extracts_leisure_swim(self):
        """Test _try_pdfplumber extracts Leisure Swim from table."""
        parser = PDFParser()

        # Mock pdfplumber
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Day', 'Lane Swim', 'Leisure Swim'],
                ['Monday', '6:00am-8:00am', '10:00 a.m. - 12:00 p.m.'],
                ['Tuesday', '6:00am-8:00am', '2:00 p.m. - 4:00 p.m.'],
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].subject, 'Leisure Swim')
        self.assertEqual(result[0].byday, ['MO'])
        self.assertEqual(result[0].start_time, '10:00')
        self.assertEqual(result[0].end_time, '12:00')
        self.assertEqual(result[1].byday, ['TU'])

    def test_try_pdfplumber_skips_tables_without_day_header(self):
        """Test _try_pdfplumber skips tables missing Day column."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Activity', 'Leisure Swim'],
                ['Morning', '10:00am - 11:00am'],
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(result, [])

    def test_try_pdfplumber_skips_tables_without_leisure_header(self):
        """Test _try_pdfplumber skips tables missing Leisure column."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Day', 'Lane Swim'],
                ['Monday', '6:00am-8:00am'],
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(result, [])

    def test_try_pdfplumber_handles_empty_leisure_cell(self):
        """Test _try_pdfplumber skips rows with empty leisure cell."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Day', 'Leisure Swim'],
                ['Monday', ''],
                ['Tuesday', '10:00 a.m. - 11:00 a.m.'],
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].byday, ['TU'])

    def test_try_pdfplumber_handles_oserror(self):
        """Test _try_pdfplumber handles OSError gracefully."""
        parser = PDFParser()

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.side_effect = OSError('File not found')

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(result, [])

    def test_try_pdfplumber_handles_empty_table(self):
        """Test _try_pdfplumber handles empty or None tables."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [None, [], [[]]]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(result, [])

    def test_try_pdfplumber_handles_short_rows(self):
        """Test _try_pdfplumber skips rows shorter than required columns."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Day', 'Lane Swim', 'Leisure Swim'],
                ['Monday'],  # Too short
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(result, [])

    def test_try_pdfplumber_handles_newlines_in_header(self):
        """Test _try_pdfplumber handles newlines in header cells."""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ['Day\nof Week', 'Lane\nSwim', 'Leisure\nSwim'],
                ['Monday', '6:00am', '10:00 a.m. - 11:00 a.m.'],
            ]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch.dict('sys.modules', {'pdfplumber': mock_pdfplumber}):
            result = parser._try_pdfplumber('/fake/path.pdf')

        self.assertEqual(len(result), 1)


class TestPDFParserParseAuroraText(unittest.TestCase):
    """Tests for PDFParser._parse_aurora_text()."""

    def test_parse_aurora_text_extracts_schedule(self):
        """Test _parse_aurora_text extracts schedule from Aurora format."""
        parser = PDFParser()
        text = """
Town of Aurora

Day
Leisure Swim
Monday
10:00 a.m. - 12:00 p.m.
Tuesday
2:00 p.m. - 4:00 p.m.
"""
        result = parser._parse_aurora_text(text, '/fake/path.pdf')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].subject, 'Leisure Swim')
        self.assertEqual(result[0].byday, ['MO'])
        self.assertEqual(result[0].start_time, '10:00')
        self.assertEqual(result[0].end_time, '12:00')

    def test_parse_aurora_text_handles_day_ranges(self):
        """Test _parse_aurora_text handles day ranges like 'Mon to Fri'."""
        parser = PDFParser()
        text = """
Day
Leisure
Mon to Fri
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/fake/path.pdf')

        self.assertEqual(len(result), 5)
        days = [item.byday[0] for item in result]
        self.assertEqual(days, ['MO', 'TU', 'WE', 'TH', 'FR'])

    def test_parse_aurora_text_skips_blocks_without_leisure(self):
        """Test _parse_aurora_text skips blocks without Leisure header."""
        parser = PDFParser()
        text = """
Day
Lane Swim
Monday
6:00 a.m. - 8:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/fake/path.pdf')
        self.assertEqual(result, [])

    def test_parse_aurora_text_skips_blocks_without_weekday(self):
        """Test _parse_aurora_text skips blocks without weekday names."""
        parser = PDFParser()
        text = """
Day
Leisure
Holiday
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/fake/path.pdf')
        self.assertEqual(result, [])

    def test_parse_aurora_text_handles_multiple_time_ranges(self):
        """Test _parse_aurora_text handles multiple time ranges in one cell."""
        parser = PDFParser()
        text = """
Day
Leisure
Saturday
10:00 a.m. - 12:00 p.m.
2:00 p.m. - 4:00 p.m.
"""
        result = parser._parse_aurora_text(text, '/fake/path.pdf')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].start_time, '10:00')
        self.assertEqual(result[1].start_time, '14:00')

    def test_parse_aurora_text_normalizes_carriage_returns(self):
        """Test _parse_aurora_text normalizes carriage returns."""
        parser = PDFParser()
        text = "Day\r\nLeisure\r\nMonday\r\n10:00 a.m. - 11:00 a.m.\r\n"
        result = parser._parse_aurora_text(text, '/fake/path.pdf')

        self.assertEqual(len(result), 1)


class TestPDFParserParse(unittest.TestCase):
    """Tests for PDFParser.parse() main entry point."""

    def test_parse_returns_pdfplumber_results_when_available(self):
        """Test parse() returns pdfplumber results when extraction succeeds."""
        parser = PDFParser()
        expected = [ScheduleItem(subject='Leisure Swim', byday=['MO'])]

        with patch.object(parser, '_try_pdfplumber', return_value=expected):
            with patch('pdfminer.high_level.extract_text', return_value=''):
                result = parser.parse('/fake/path.pdf')

        self.assertEqual(result, expected)

    def test_parse_falls_back_to_text_extraction(self):
        """Test parse() falls back to text extraction when pdfplumber fails."""
        parser = PDFParser()
        aurora_text = """Town of Aurora
Swimming Drop-In Schedules
Day
Leisure Swim
Monday
10:00 a.m. - 11:00 a.m.
"""
        with patch.object(parser, '_try_pdfplumber', return_value=[]):
            with patch('pdfminer.high_level.extract_text', return_value=aurora_text):
                result = parser.parse('/fake/path.pdf')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].subject, 'Leisure Swim')

    def test_parse_raises_for_unsupported_pdf(self):
        """Test parse() raises NotImplementedError for unsupported PDFs."""
        parser = PDFParser()

        with patch.object(parser, '_try_pdfplumber', return_value=[]):
            with patch('pdfminer.high_level.extract_text', return_value='Random PDF content'):
                with self.assertRaises(NotImplementedError) as ctx:
                    parser.parse('/fake/path.pdf')
                self.assertIn('Aurora drop-in schedules', str(ctx.exception))

    def test_parse_raises_on_extraction_failure(self):
        """Test parse() raises RuntimeError on text extraction failure."""
        parser = PDFParser()

        with patch.object(parser, '_try_pdfplumber', return_value=[]):
            with patch('pdfminer.high_level.extract_text', side_effect=Exception('Corrupt PDF')):
                with self.assertRaises(RuntimeError) as ctx:
                    parser.parse('/fake/path.pdf')
                self.assertIn('Failed to extract text', str(ctx.exception))

    def test_parse_recognizes_drop_in_lane_schedules(self):
        """Test parse() recognizes alternate Aurora header format."""
        parser = PDFParser()
        aurora_text = """Town of Aurora
drop-in Lane and Leisure swims
Day
Leisure
Saturday
10:00 a.m. - 11:00 a.m.
"""
        with patch.object(parser, '_try_pdfplumber', return_value=[]):
            with patch('pdfminer.high_level.extract_text', return_value=aurora_text):
                result = parser.parse('/fake/path.pdf')

        self.assertEqual(len(result), 1)


class TestPDFParserResultFields(unittest.TestCase):
    """Tests for correct field population in parsed results."""

    def test_result_has_correct_recurrence(self):
        """Test parsed items have weekly recurrence."""
        parser = PDFParser()
        text = """
Day
Leisure
Monday
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/path/test.pdf')

        self.assertEqual(result[0].recurrence, 'weekly')

    def test_result_has_location(self):
        """Test parsed items have Aurora Pools location."""
        parser = PDFParser()
        text = """
Day
Leisure
Monday
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/path/test.pdf')

        self.assertEqual(result[0].location, 'Aurora Pools')

    def test_result_has_notes_with_path(self):
        """Test parsed items include source path in notes."""
        parser = PDFParser()
        text = """
Day
Leisure
Monday
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/path/test.pdf')

        self.assertIn('/path/test.pdf', result[0].notes)

    def test_result_has_range_start(self):
        """Test parsed items have range_start set to today."""
        parser = PDFParser()
        text = """
Day
Leisure
Monday
10:00 a.m. - 11:00 a.m.
"""
        result = parser._parse_aurora_text(text, '/path/test.pdf')

        self.assertEqual(result[0].range_start, datetime.date.today().isoformat())


if __name__ == '__main__':
    unittest.main()
