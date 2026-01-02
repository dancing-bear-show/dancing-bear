"""Tests for metals cost_extractor base class and extracted helper methods."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock, patch

from metals.cost_extractor import CostExtractor, MessageInfo, OrderData
from metals.outlook_costs import OutlookCostExtractor


class MockCostExtractor(CostExtractor):
    """Mock implementation for testing base class."""

    def __init__(self, profile: str, out_path: str, days: int = 365):
        super().__init__(profile, out_path, days)
        self.authenticated = False
        self.fetched_ids = []
        self.processed_orders = []

    def _authenticate(self) -> None:
        self.authenticated = True

    def _fetch_message_ids(self):
        return self.fetched_ids

    def _get_message_info(self, msg_id: str) -> MessageInfo:
        return MessageInfo(
            msg_id=msg_id,
            subject=f"Subject {msg_id}",
            from_header="test@example.com",
            body_text=f"Body {msg_id}",
            received_date="2024-01-15"
        )

    def _extract_order_id(self, msg: MessageInfo) -> str | None:
        # Extract from msg_id for testing
        # Handle duplicates: 'ord-msg1-dup' -> 'ord-order1'
        if msg.msg_id.startswith("ord"):
            order_id = msg.msg_id.replace("msg", "order")
            # Remove -dup suffix to group duplicates
            order_id = order_id.replace("-dup", "")
            return order_id
        return None

    def _select_best_message(self, messages):
        return messages[0] if messages else None

    def _process_order_to_rows(self, order: OrderData):
        self.processed_orders.append(order.order_id)
        return [{'order_id': order.order_id, 'vendor': order.vendor}]


class TestCostExtractorBaseClass(unittest.TestCase):
    """Tests for CostExtractor base class template method pattern."""

    def test_run_orchestrates_workflow(self):
        """Test run() orchestrates the full workflow."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        extractor.fetched_ids = ['ord-msg1', 'ord-msg2']

        with patch('metals.cost_extractor.merge_costs_csv') as mock_merge:
            result = extractor.run()

            # Verify workflow steps
            self.assertTrue(extractor.authenticated)
            self.assertEqual(result, 0)
            mock_merge.assert_called_once()

            # Verify processing
            args, _ = mock_merge.call_args
            rows = args[1]
            self.assertEqual(len(rows), 2)  # 2 orders processed

    def test_run_returns_one_when_no_messages(self):
        """Test run() returns 1 when no messages found."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        extractor.fetched_ids = []

        result = extractor.run()
        self.assertEqual(result, 1)
        self.assertTrue(extractor.authenticated)

    def test_run_returns_one_when_no_orders(self):
        """Test run() returns 1 when no orders extracted."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        extractor.fetched_ids = ['msg1', 'msg2']  # No 'ord' prefix

        result = extractor.run()
        self.assertEqual(result, 1)
        self.assertEqual(len(extractor.processed_orders), 0)

    def test_group_by_order_groups_messages(self):
        """Test _group_by_order groups messages by order ID."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        extractor.fetched_ids = ['ord-msg1', 'ord-msg2', 'ord-msg1-dup']

        by_order = extractor._group_by_order(extractor.fetched_ids)

        # Should have 2 orders (order1 and order2)
        self.assertEqual(len(by_order), 2)
        self.assertIn('ord-order1', by_order)
        self.assertIn('ord-order2', by_order)

        # Order 1 should have 2 messages (original + duplicate)
        self.assertEqual(len(by_order['ord-order1']), 2)

    def test_build_order_data_selects_best_message(self):
        """Test _build_order_data selects best message."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        messages = [
            MessageInfo('msg1', 'Subject 1', 'test@ex.com', 'Body 1', '2024-01-15'),
            MessageInfo('msg2', 'Subject 2', 'test@ex.com', 'Body 2', '2024-01-16'),
        ]

        order_data = extractor._build_order_data('ORD123', messages)

        self.assertEqual(order_data.order_id, 'ORD123')
        self.assertEqual(len(order_data.messages), 2)
        self.assertEqual(order_data.vendor, 'Unknown')  # Default

    def test_classify_vendor_returns_unknown_by_default(self):
        """Test _classify_vendor returns Unknown by default."""
        extractor = MockCostExtractor('test', 'out/test.csv')
        vendor = extractor._classify_vendor('unknown@example.com')
        self.assertEqual(vendor, 'Unknown')


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
            # First page
            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.json.return_value = {
                'value': [{'id': 'msg1'}],
                '@odata.nextLink': 'https://next-page'
            }

            # Second page
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
                {'subject': 'No ID'},  # Missing ID
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
            mock_response.json.return_value = {
                'value': [{'id': 'msg1'}]
            }
            mock_get.return_value = mock_response

            ids = extractor._search_confirmation_messages('PO123')

            self.assertEqual(ids, ['msg1'])

    def test_select_confirmation_message_prefers_confirmation_subject(self):
        """Test _select_confirmation_message prefers confirmation in subject."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        extractor.client = MagicMock()

        # First message doesn't have confirmation in subject
        msg1 = {'subject': 'Shipping for order'}
        # Second message has confirmation
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

        self.assertEqual(result, 'msg1')  # Returns first on error

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

        # Should find gold item
        self.assertGreater(len(gold_items), 0)
        self.assertGreater(oz_by_metal['gold'], 0)

    def test_extract_items_and_metals_handles_fallback(self):
        """Test _extract_items_and_metals applies 1/10 oz fallback."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        body = "Gold product 1/10-oz\nNo explicit items"

        result = extractor._extract_items_and_metals(body)

        self.assertIsNotNone(result)
        _, _, oz_by_metal, units_by_metal, _ = result

        # Should have fallback 0.1 oz gold
        self.assertAlmostEqual(oz_by_metal['gold'], 0.1)
        self.assertEqual(units_by_metal['gold'][0.1], 1.0)

    def test_determine_total_cost_validates_line_cost(self):
        """Test _determine_total_cost validates line cost against order total."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        body = "Total C$1000.00"

        # Line cost within range (60% - 105% of total)
        result = extractor._determine_total_cost(body, 900.0)
        self.assertEqual(result, 900.0)

        # Line cost too low
        result = extractor._determine_total_cost(body, 400.0)
        self.assertEqual(result, 1000.0)  # Uses order total

        # Line cost too high
        result = extractor._determine_total_cost(body, 1200.0)
        self.assertEqual(result, 1000.0)  # Uses order total

    def test_build_output_rows_returns_per_item_rows(self):
        """Test _build_output_rows returns per-item rows when available."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        msg = MessageInfo('msg1', 'Test', 'test@example.com', 'Body', '2024-01-15')
        per_item_rows = [
            {'vendor': 'RCM', 'cost_total': 350.0, 'order_id': 'PO123'}
        ]

        rows = extractor._build_output_rows(
            per_item_rows, 350.0, {'gold': 0.1}, {'gold': {0.1: 1.0}},
            'PO123', msg, 350.0
        )

        self.assertEqual(rows, per_item_rows)

    def test_build_output_rows_builds_aggregated_row(self):
        """Test _build_output_rows builds aggregated row when no per-item."""
        extractor = OutlookCostExtractor('test', 'out/test.csv')
        msg = MessageInfo('msg1', 'Test', 'test@example.com', 'Body', '2024-01-15')

        rows = extractor._build_output_rows(
            [], 350.0, {'gold': 0.1}, {'gold': {0.1: 1.0}},
            'PO123', msg, 0.0
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cost_total'], 350.0)
        self.assertEqual(rows[0]['order_id'], 'PO123')


class TestMessageInfo(unittest.TestCase):
    """Tests for MessageInfo dataclass."""

    def test_message_info_creation(self):
        """Test MessageInfo can be created."""
        msg = MessageInfo(
            msg_id='msg123',
            subject='Test Subject',
            from_header='test@example.com',
            body_text='Test body',
            received_date='2024-01-15'
        )

        self.assertEqual(msg.msg_id, 'msg123')
        self.assertEqual(msg.subject, 'Test Subject')
        self.assertEqual(msg.from_header, 'test@example.com')
        self.assertEqual(msg.body_text, 'Test body')
        self.assertEqual(msg.received_date, '2024-01-15')

    def test_message_info_with_received_ms(self):
        """Test MessageInfo with received_ms field."""
        msg = MessageInfo(
            msg_id='msg123',
            subject='Test',
            from_header='test@example.com',
            body_text='Body',
            received_date='2024-01-15',
            received_ms=1705334400000
        )

        self.assertEqual(msg.received_ms, 1705334400000)


class TestOrderData(unittest.TestCase):
    """Tests for OrderData dataclass."""

    def test_order_data_creation(self):
        """Test OrderData can be created."""
        messages = [
            MessageInfo('msg1', 'Subject 1', 'test@ex.com', 'Body 1', '2024-01-15'),
            MessageInfo('msg2', 'Subject 2', 'test@ex.com', 'Body 2', '2024-01-16'),
        ]

        order = OrderData(
            order_id='ORD123',
            messages=messages,
            vendor='TestVendor'
        )

        self.assertEqual(order.order_id, 'ORD123')
        self.assertEqual(len(order.messages), 2)
        self.assertEqual(order.vendor, 'TestVendor')


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

    @patch('metals.gmail_costs.GmailClient')
    @patch('metals.gmail_costs.resolve_paths_profile')
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
        msg = MessageInfo(
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
        msg = MessageInfo(
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
        msg = MessageInfo(
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
        msg = MessageInfo(
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
            MessageInfo('msg1', 'Shipping Notice', 'noreply@td.com', 'Shipped', '', 100),
            MessageInfo('msg2', 'Order Confirmation', 'noreply@td.com', 'Confirmed', '', 200),
        ]

        best = extractor._select_best_message(messages)

        # Should prefer confirmation over shipping
        self.assertEqual(best.msg_id, 'msg2')

    def test_gmail_select_best_message_returns_first_if_no_confirmation(self):
        """Test _select_best_message returns first when no confirmation."""
        from metals.gmail_costs import GmailCostExtractor

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        messages = [
            MessageInfo('msg1', 'Shipping Notice', 'noreply@td.com', 'Shipped', '', 100),
            MessageInfo('msg2', 'Receipt', 'noreply@td.com', 'Receipt', '', 200),
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

    @patch('metals.gmail_costs._process_order')
    def test_gmail_process_order_to_rows_delegates(self, mock_process):
        """Test _process_order_to_rows delegates to _process_order."""
        from metals.gmail_costs import GmailCostExtractor

        mock_process.return_value = [{'order_id': 'ORD123', 'cost': 100}]

        extractor = GmailCostExtractor('gmail_test', 'out/test.csv')
        extractor.client = Mock()

        messages = [
            MessageInfo('msg1', 'Subject', 'test@example.com', 'Body', '', 1000)
        ]
        order = OrderData('ORD123', messages, 'TD')

        rows = extractor._process_order_to_rows(order)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['order_id'], 'ORD123')
        mock_process.assert_called_once()


if __name__ == '__main__':
    unittest.main()
