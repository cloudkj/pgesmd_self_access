"""A server that handles POST from PGE SMD servers."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.etree import cElementTree as ET
import ssl
import logging
import os

from .helpers import parse_espi_data, get_bulk_id_from_xml

_LOGGER = logging.getLogger(__name__)


class PgePostHandler(BaseHTTPRequestHandler):
    """Handle POST from PGE."""

    api = None
    save_file = None
    filename = None
    to_db = None
    update_path = None
    
    def do_POST(self):
        """Download the ESPI XML and save to database."""
        _LOGGER.debug(f"Received POST from {self.address_string()}")

        if self.path == "/test":
            self.send_response(200)
            self.end_headers()
            return
        
        if self.path == "/refresh":
            self.api.request_latest_data()
            self.send_response(200)
            self.end_headers()
            return

        if not self.path == update_path:
            _LOGGER.debug(f"Unhandled path {self.path}")
            return

        body = self.rfile.read(int(self.headers.get("Content-Length")))
        _LOGGER.debug(body)
        try:
            batch_list = ET.fromstring(body)
        except ET.ParseError:
            _LOGGER.error(f"Could not parse message: {body}")
            return
        
        resource_uris = []
        for resource_uri in batch_list:
            resource_uri = resource_uri.text
            if not resource_uri[: len(self.api.utility_uri)] == self.api.utility_uri:
                _LOGGER.error(
                    f"POST from {self.address_string} contains: "
                    f"{body}     "
                    f"{resource_uri[:len(self.api.utility_uri)]}"
                    f" != {self.api.utility_uri}"
                )
                continue
            if resource_uri.partition('correlationID=')[2] == '000000000-b':
                _LOGGER.debug(f'Skipping {resource_uri}')
                continue
            resource_uris.append(resource_uri)
        
        if len(resource_uris) == 0:
            _LOGGER.error("No resources to process")
            return

        self.send_response(200)
        self.end_headers()

        for resource_uri in resource_uris:
            xml_data = self.api.get_espi_data(resource_uri)

            if self.save_file:
                save_name = self.save_file(xml_data, filename=self.filename)
                if save_name:
                    _LOGGER.info(f"XML saved at {save_name}")
                else:
                    _LOGGER.error("File not saved.")

            try:
                data = list(parse_espi_data(xml_data))
                for _ in data:
                    _LOGGER.debug(f"Parsed data: {_}")
            except Exception as e:
                _LOGGER.error(f"Failed to parse XML: {e}")

            if self.to_db:
                self.to_db(data)
                _LOGGER.info(f"Wrote {len(data)} values to database")

                
class SelfAccessServer:
    """Server class for PGE SMD Self Access API."""

    def __init__(
        self,
        api_instance,
        port=7999,
        save_file=None,
        filename=None,
        to_db=None,
        close_after=False,
        update_path="/pgesmd",
    ):
        """Initialize and start the server on construction."""
        PgePostHandler.api = api_instance
        PgePostHandler.save_file = save_file
        PgePostHandler.filename = filename
        PgePostHandler.to_db = to_db
        PgePostHandler.update_path = update_path
        server = HTTPServer(("", port), PgePostHandler)

        if close_after:
            server.handle_request()
        else:
            server.serve_forever()
