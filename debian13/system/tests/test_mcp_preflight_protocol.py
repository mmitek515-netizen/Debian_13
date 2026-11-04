"""Regression checks for the local MCP client's initialization handshake."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp_preflight


class PreflightProtocolTests(unittest.TestCase):
    def test_initialization_notification_precedes_tool_discovery(self):
        methods = []

        def request(port, token, message):
            methods.append(message['method'])
            if message['method'] == 'initialize':
                return {'protocolVersion': mcp_preflight.MCP_PROTOCOL}
            if message['method'] == 'notifications/initialized':
                self.assertNotIn('id', message)
                return {}
            self.assertEqual(methods, ['initialize', 'notifications/initialized', 'tools/list'])
            raise mcp_preflight.ProbeError('discovery reached')

        with patch.object(mcp_preflight, '_request', side_effect=request):
            with self.assertRaisesRegex(mcp_preflight.ProbeError, 'discovery reached'):
                mcp_preflight.check_local(8766, 'x' * 48)

    def test_notification_requires_202_and_empty_body(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        for status, body, accepted in [(202, b'', True), (200, b'', False),
                                       (202, b'x', False)]:
            with self.subTest(status=status, body=body):
                response = Mock(status=status)
                response.read.return_value = body
                opener = Mock()
                opener.open.return_value = nullcontext(response)
                with patch.object(mcp_preflight.urllib.request, 'build_opener', return_value=opener):
                    message = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
                    if accepted:
                        self.assertEqual(mcp_preflight._request(8766, 'x' * 48, message), {})
                    else:
                        with self.assertRaises(mcp_preflight.ProbeError):
                            mcp_preflight._request(8766, 'x' * 48, message)


if __name__ == '__main__':
    unittest.main()
