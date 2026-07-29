"""Tests for GmailCostExtractor integration and OutlookCostExtractor helpers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock, patch

from metals.cost_extractor import OrderData
from metals.outlook_costs import OutlookCostExtractor, OutputRowsContext
from tests.metals_tests.fixtures import make_message_info


class TestOutlookCostExtractorHelpers(unittest.TestCase):
    """Tests for OutlookCostExtractor helper methods."""

    def test_fetch_ids_for_query_fetches_single_page(self):
        """Test _fetch_ids_for_query fetches a single page."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.GRAPH = "https://graph.microsoft.com/v1.0"
        extractor.client._headers_search.return_value = {}

        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'value': [{'id': 'msg1'}, {'id': 'msg2'}],
                '@odata.nextLink': None
            }
            mock_get.return_value = mock_response

            ids = extractor._fetch_ids_for_query('test query')

            self.assertEqual(ids, ['msg1', 'msg2'])
            mock_get.assert_called_once()

    def test_fetch_ids_for_query_follows_pagination(self):
        """Test _fetch_ids_for_query follows pagination links."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.GRAPH = "https://graph.microsoft.com/v1.0"
        extractor.client._headers_search.return_value = {}

        with patch('requests.get') as mock_get:
            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.json.return_value = {
                'value': [{'id': 'msg1'}],
                '@odata.nextLink': 'https://next-page'
            }
            resp2 = MagicMock()
            resp2.status_code = 200
            resp2.json.return_value = {
                'value': [{'id': 'msg2'}],
                '@odata.nextLink': None
            }
            mock_get.side_effect = [resp1, resp2]

            ids = extractor._fetch_ids_for_query('test query')

            self.assertEqual(ids, ['msg1', 'msg2'])
            self.assertEqual(mock_get.call_count, 2)

    def test_fetch_ids_for_query_stops_on_error(self):
        """Test _fetch_ids_for_query stops on HTTP error."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.GRAPH = "https://graph.microsoft.com/v1.0"
        extractor.client._headers_search.return_value = {}

        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_get.return_value = mock_response

            ids = extractor._fetch_ids_for_query('test query')

            self.assertEqual(ids, [])

    def test_extract_ids_from_response_extracts_ids(self):
        """Test _extract_ids_from_response extracts message IDs."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        data = {
            'value': [
                {'id': 'msg1', 'subject': 'Test'},
                {'id': 'msg2', 'subject': 'Test 2'},
                {'subject': 'No ID'},
            ]
        }

        ids = extractor._extract_ids_from_response(data)

        self.assertEqual(ids, ['msg1', 'msg2'])

    def test_extract_ids_from_response_handles_empty(self):
        """Test _extract_ids_from_response handles empty response."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')

        ids = extractor._extract_ids_from_response({})
        self.assertEqual(ids, [])

        ids = extractor._extract_ids_from_response({'value': None})
        self.assertEqual(ids, [])

    def test_search_confirmation_messages_uses_client_search(self):
        """Test _search_confirmation_messages tries client search first."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.search_inbox_messages.return_value = ['msg1', 'msg2']

        ids = extractor._search_confirmation_messages('PO123')

        self.assertEqual(ids, ['msg1', 'msg2'])
        extractor.client.search_inbox_messages.assert_called_once()

    def test_search_confirmation_messages_falls_back_to_api(self):
        """Test _search_confirmation_messages falls back to direct API."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.GRAPH = "https://graph.microsoft.com/v1.0"
        extractor.client._headers_search.return_value = {}
        extractor.client.search_inbox_messages.side_effect = Exception("Error")

        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'value': [{'id': 'msg1'}]}
            mock_get.return_value = mock_response

            ids = extractor._search_confirmation_messages('PO123')

            self.assertEqual(ids, ['msg1'])

    def test_select_confirmation_message_prefers_confirmation_subject(self):
        """Test _select_confirmation_message prefers confirmation in subject."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()

        msg1 = {'subject': 'Shipping for order'}
        msg2 = {'subject': 'Confirmation for order number PO123'}

        extractor.client.get_message.side_effect = [msg1, msg2]

        result = extractor._select_confirmation_message(['msg1', 'msg2'])

        self.assertEqual(result, 'msg2')

    def test_select_confirmation_message_returns_first_if_none_match(self):
        """Test _select_confirmation_message returns first if no match."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()

        msg1 = {'subject': 'Shipping for order'}
        extractor.client.get_message.return_value = msg1

        result = extractor._select_confirmation_message(['msg1', 'msg2'])

        self.assertEqual(result, 'msg1')

    def test_select_confirmation_message_handles_errors(self):
        """Test _select_confirmation_message handles get_message errors."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.get_message.side_effect = Exception("API Error")

        result = extractor._select_confirmation_message(['msg1'])

        self.assertEqual(result, 'msg1')

    def test_fetch_confirmation_message_returns_message_info(self):
        """Test _fetch_confirmation_message returns MessageInfo."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.get_message.return_value = {
            'subject': 'Confirmation for order PO123',
            'body': {'content': '<p>Confirmed</p>'},
            'receivedDateTime': '2024-01-15T10:00:00Z'
        }

        with patch('metals.outlook_costs.html_to_text', return_value='Confirmed'):
            result = extractor._fetch_confirmation_message('msg1', 'test@example.com')

            self.assertIsNotNone(result)
            self.assertEqual(result.msg_id, 'msg1')
            self.assertEqual(result.subject, 'Confirmation for order PO123')
            self.assertEqual(result.from_header, 'test@example.com')

    def test_fetch_confirmation_message_handles_error(self):
        """Test _fetch_confirmation_message handles errors."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()
        extractor.client.get_message.side_effect = Exception("API Error")

        result = extractor._fetch_confirmation_message('msg1', 'test@example.com')

        self.assertIsNone(result)

    def test_extract_items_and_metals_parses_items(self):
        """Test _extract_items_and_metals extracts items correctly."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        body = "1/10 oz Gold Maple Leaf\nTotal $350.00 CAD"

        result = extractor._extract_items_and_metals(body)

        self.assertIsNotNone(result)
        _, gold_items, oz_by_metal, _, _ = result

        self.assertGreater(len(gold_items), 0)
        self.assertGreater(oz_by_metal['gold'], 0)

    def test_extract_items_and_metals_handles_fallback(self):
        """Test _extract_items_and_metals applies 1/10 oz fallback."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        body = "Gold product 1/10-oz\nNo explicit items"

        result = extractor._extract_items_and_metals(body)

        self.assertIsNotNone(result)
        _, _, oz_by_metal, units_by_metal, _ = result

        self.assertAlmostEqual(oz_by_metal['gold'], 0.1)
        self.assertEqual(units_by_metal['gold'][0.1], 1.0)

    def test_determine_total_cost_validates_line_cost(self):
        """Test _determine_total_cost validates line cost against order total."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        body = "Total C$1000.00"

        result = extractor._determine_total_cost(body, 900.0)
        self.assertEqual(result, 900.0)

        result = extractor._determine_total_cost(body, 400.0)
        self.assertEqual(result, 1000.0)

        result = extractor._determine_total_cost(body, 1200.0)
        self.assertEqual(result, 1000.0)

    def test_build_output_rows_returns_per_item_rows(self):
        """Test _build_output_rows returns per-item rows when available."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        msg = make_message_info(msg_id='msg1', subject='Test', from_header='test@example.com', body_text='Body', received_date='2024-01-15')
        per_item_rows = [{'vendor': 'RCM', 'cost_total': 350.0, 'order_id': 'PO123'}]

        orc = OutputRowsContext(
            per_item_rows=per_item_rows, total_cost=350.0,
            oz_by_metal={'gold': 0.1}, units_by_metal={'gold': {0.1: 1.0}},
            order_id='PO123', msg=msg, line_cost=350.0,
        )
        rows = extractor._build_output_rows(orc)

        self.assertEqual(rows, per_item_rows)

    def test_build_output_rows_builds_aggregated_row(self):
        """Test _build_output_rows builds aggregated row when no per-item."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        msg = make_message_info(msg_id='msg1', subject='Test', from_header='test@example.com', body_text='Body', received_date='2024-01-15')

        orc = OutputRowsContext(
            per_item_rows=[], total_cost=350.0,
            oz_by_metal={'gold': 0.1}, units_by_metal={'gold': {0.1: 1.0}},
            order_id='PO123', msg=msg, line_cost=0.0,
        )
        rows = extractor._build_output_rows(orc)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cost_total'], 350.0)
        self.assertEqual(rows[0]['order_id'], 'PO123')


class TestGmailCostExtractorIntegration(unittest.TestCase):
    """Integration tests for GmailCostExtractor class."""

    def test_gmail_extractor_creation(self):
        """Test GmailCostExtractor can be created."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv', days=30)

        self.assertEqual(extractor.profile, 'gmail_test')
        self.assertEqual(extractor.out_path, 'out/test.csv')
        self.assertEqual(extractor.days, 30)
        self.assertIsNone(extractor.client)

    @patch('metals.gmail_costs_extract.GmailClient')
    @patch('mail.config_resolver.resolve_paths_profile')
    def test_gmail_authenticate_creates_client(self, mock_resolve, mock_client_cls):
        """Test _authenticate creates Gmail client."""
        from metals.gmail_costs import GmailCostExtractor

        mock_resolve.return_value = ('/creds.json', '/token.json')
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        extractor._authenticate()

        self.assertIsNotNone(extractor.client)
        mock_client.authenticate.assert_called_once()

    def test_gmail_extract_order_id_from_subject(self):
        """Test _extract_order_id extracts from subject."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        msg = make_message_info(
            msg_id='msg123',
            subject='Order #1234567 Confirmation',
            from_header='noreply@td.com',
            body_text='Order details',
            received_date=''
        )

        order_id = extractor._extract_order_id(msg)

        self.assertEqual(order_id, '1234567')

    def test_gmail_extract_order_id_from_body(self):
        """Test _extract_order_id extracts from body."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        msg = make_message_info(
            msg_id='msg123',
            subject='Your order',
            from_header='noreply@td.com',
            body_text='Thank you for order #9876543',
            received_date=''
        )

        order_id = extractor._extract_order_id(msg)

        self.assertEqual(order_id, '9876543')

    def test_gmail_extract_order_id_costco(self):
        """Test _extract_order_id handles Costco format."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        msg = make_message_info(
            msg_id='msg123',
            subject='Costco.ca Order 1122334455',
            from_header='orders@costco.ca',
            body_text='Order details',
            received_date=''
        )

        order_id = extractor._extract_order_id(msg)

        self.assertEqual(order_id, '1122334455')

    def test_gmail_extract_order_id_falls_back_to_msg_id(self):
        """Test _extract_order_id uses msg_id when no order found."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        msg = make_message_info(
            msg_id='unique-msg-id',
            subject='No order number here',
            from_header='test@example.com',
            body_text='No order',
            received_date=''
        )

        order_id = extractor._extract_order_id(msg)

        self.assertEqual(order_id, 'unique-msg-id')

    def test_gmail_select_best_message_prefers_confirmation(self):
        """Test _select_best_message prefers confirmation messages."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        messages = [
            make_message_info(msg_id='msg1', subject='Shipping Notice', from_header='noreply@td.com', body_text='Shipped', received_date='', received_ms=100),
            make_message_info(msg_id='msg2', subject='Order Confirmation', from_header='noreply@td.com', body_text='Confirmed', received_date='', received_ms=200),
        ]

        best = extractor._select_best_message(messages)

        self.assertEqual(best.msg_id, 'msg2')

    def test_gmail_select_best_message_returns_first_if_no_confirmation(self):
        """Test _select_best_message returns first when no confirmation."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        messages = [
            make_message_info(msg_id='msg1', subject='Shipping Notice', from_header='noreply@td.com', body_text='Shipped', received_date='', received_ms=100),
            make_message_info(msg_id='msg2', subject='Receipt', from_header='noreply@td.com', body_text='Receipt', received_date='', received_ms=200),
        ]

        best = extractor._select_best_message(messages)

        self.assertEqual(best.msg_id, 'msg1')

    def test_gmail_classify_vendor_td(self):
        """Test _classify_vendor identifies TD."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        vendor = extractor._classify_vendor('noreply@td.com')
        self.assertEqual(vendor, 'TD')

    def test_gmail_classify_vendor_costco(self):
        """Test _classify_vendor identifies Costco."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        vendor = extractor._classify_vendor('orders@costco.ca')
        self.assertEqual(vendor, 'Costco')

    def test_gmail_classify_vendor_rcm(self):
        """Test _classify_vendor identifies RCM."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        vendor = extractor._classify_vendor('email@mint.ca')
        self.assertEqual(vendor, 'RCM')

    def test_gmail_classify_vendor_unknown(self):
        """Test _classify_vendor returns Other for unknown."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        vendor = extractor._classify_vendor('unknown@example.com')
        self.assertEqual(vendor, 'Other')

    @patch('metals.gmail_costs_extract._process_order')
    def test_gmail_process_order_to_rows_delegates(self, mock_process):
        """Test _process_order_to_rows delegates to _process_order."""
        from metals.gmail_costs import GmailCostExtractor

        mock_process.return_value = [{'order_id': 'ORD123', 'cost': 100}]

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        extractor.client = Mock()

        messages = [
            make_message_info(msg_id='msg1', subject='Subject', from_header='test@example.com', body_text='Body', received_date='', received_ms=1000)
        ]
        order = OrderData('ORD123', messages, 'TD')

        rows = extractor._process_order_to_rows(order)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['order_id'], 'ORD123')
        mock_process.assert_called_once()


if __name__ == '__main__':
    unittest.main()
