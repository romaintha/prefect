import json
import logging
import time
from unittest.mock import MagicMock

import pytest

from prefect import context, utilities


def test_root_logger_level_responds_to_config():
    try:
        with utilities.configuration.set_temporary_config({"logging.level": "DEBUG"}):
            assert (
                utilities.logging.configure_logging(testing=True).level == logging.DEBUG
            )

        with utilities.configuration.set_temporary_config({"logging.level": "WARNING"}):
            assert (
                utilities.logging.configure_logging(testing=True).level
                == logging.WARNING
            )
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_remote_handler_is_configured_for_cloud():
    try:
        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger = utilities.logging.configure_logging(testing=True)
            assert hasattr(logger.handlers[-1], "client")
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_remote_handler_captures_errors_and_logs_them(caplog, monkeypatch):
    try:
        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True, "cloud.auth_token": None}
        ):
            logger = utilities.logging.configure_logging(testing=True)
            assert hasattr(logger.handlers[-1], "client")
            logger.handlers[-1].client = MagicMock()
            child_logger = logger.getChild("sub-test")
            child_logger.critical("this should raise an error in the handler")

            time.sleep(1.5)  # wait for batch upload to occur
            critical_logs = [r for r in caplog.records if r.levelname == "CRITICAL"]
            assert len(critical_logs) == 2

            assert (
                "Failed to write log with error"
                in [
                    log.message for log in critical_logs if log.name == "CloudHandler"
                ].pop()
            )
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_remote_handler_captures_tracebacks(caplog, monkeypatch):
    monkeypatch.setattr("prefect.client.Client", MagicMock)
    client = MagicMock()
    try:
        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger = utilities.logging.configure_logging(testing=True)
            assert hasattr(logger.handlers[-1], "client")
            logger.handlers[-1].client = client

            child_logger = logger.getChild("sub-test")
            try:
                ## informative comment
                1 + "2"
            except:
                child_logger.exception("unexpected error")

            time.sleep(0.75)
            error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
            assert len(error_logs) == 1

            cloud_logs = client.write_run_logs.call_args[0][0]
            assert len(cloud_logs) == 1
            logged_msg = cloud_logs[0]["message"]
            assert "TypeError" in logged_msg
            assert '1 + "2"' in logged_msg
            assert "unexpected error" in logged_msg

    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_remote_handler_ships_json_payloads(caplog, monkeypatch):
    monkeypatch.setattr("prefect.client.Client", MagicMock)
    client = MagicMock()
    try:
        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger = utilities.logging.configure_logging(testing=True)
            assert hasattr(logger.handlers[-1], "client")
            logger.handlers[-1].client = client

            child_logger = logger.getChild("sub-test")
            try:
                ## informative comment
                f = lambda x: x + "2"
                f(1)
            except:
                child_logger.exception("unexpected error")

            time.sleep(0.75)
            error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
            assert len(error_logs) == 1

            cloud_logs = client.write_run_logs.call_args[0][0]
            assert len(cloud_logs) == 1
            info = cloud_logs[0]["info"]
            assert json.loads(json.dumps(info))

    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_cloud_handler_responds_to_config(caplog, monkeypatch):
    calls = []

    class Client:
        def write_run_logs(self, *args, **kwargs):
            calls.append(1)

    monkeypatch.setattr("prefect.client.Client", Client)
    try:
        logger = utilities.logging.configure_logging(testing=True)
        cloud_handler = logger.handlers[-1]
        assert isinstance(cloud_handler, utilities.logging.CloudHandler)

        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": False}
        ):
            logger.critical("testing")

        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger.critical("testing")

        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": False}
        ):
            logger.critical("testing")

        time.sleep(0.75)
        assert len(calls) == 1
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_cloud_handler_removes_bad_logs_from_queue_and_logs_error(caplog, monkeypatch):
    calls = []

    class Client:
        def write_run_logs(self, *args, **kwargs):
            calls.append(dict(args=args, kwargs=kwargs))

    monkeypatch.setattr("prefect.client.Client", Client)
    try:
        logger = utilities.logging.configure_logging(testing=True)
        cloud_handler = logger.handlers[-1]
        assert isinstance(cloud_handler, utilities.logging.CloudHandler)

        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger.critical("one")
            logger.critical(b"two")
            logger.critical("three")

        time.sleep(0.75)
        assert len(calls) == 1
        msgs = [c["message"] for c in calls[0]["args"][0]]

        assert msgs[0] == "one"
        assert "is not JSON serializable" in msgs[1]
        assert msgs[2] == "three"
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_cloud_handler_client_error(caplog, monkeypatch):
    class Client:
        def write_run_logs(self, *args, **kwargs):
            raise utilities.exceptions.ClientError("Error")

    monkeypatch.setattr("prefect.client.Client", Client)
    try:
        logger = utilities.logging.configure_logging(testing=True)
        cloud_handler = logger.handlers[-1]
        assert isinstance(cloud_handler, utilities.logging.CloudHandler)

        with utilities.configuration.set_temporary_config(
            {"logging.log_to_cloud": True}
        ):
            logger.critical("one")
    finally:
        # reset root_logger
        logger = utilities.logging.configure_logging(testing=True)
        logger.handlers = []


def test_make_error_log(caplog):

    with context({"flow_run_id": "f_id", "task_run_id": "t_id"}):
        log = utilities.logging.CloudHandler()._make_error_log("test_message")
        assert log["flowRunId"] == "f_id"
        assert log["timestamp"]
        assert log["name"] == "CloudHandler"
        assert log["message"] == "test_message"
        assert log["level"] == "CRITICAL"
        assert log["info"] == {}


def test_get_logger_returns_root_logger():
    assert utilities.logging.get_logger() is logging.getLogger("prefect")


def test_get_logger_with_name_returns_child_logger():
    child_logger = logging.getLogger("prefect.test")
    prefect_logger = utilities.logging.get_logger("test")

    assert prefect_logger is child_logger
    assert prefect_logger is logging.getLogger("prefect").getChild("test")


def test_context_attributes():
    items = {
        "flow_run_id": "fri",
        "flow_name": "fn",
        "task_run_id": "tri",
        "task_name": "tn",
        "task_slug": "ts",
    }

    class DummyFilter(logging.Filter):
        called = False

        def filter(self, record):
            self.called = True
            for k, v in items.items():
                assert getattr(record, k, None) == v

    test_filter = DummyFilter()
    logger = logging.getLogger("prefect")
    logger.addFilter(test_filter)

    with context(items):
        logger.info("log entry!")

    logger.filters.pop()

    assert test_filter.called


def test_context_only_specified_attributes():
    items = {
        "flow_run_id": "fri",
        "flow_name": "fn",
        "task_run_id": "tri",
    }

    class DummyFilter(logging.Filter):
        called = False

        def filter(self, record):
            self.called = True
            for k, v in items.items():
                assert getattr(record, k, None) == v

            not_expected = set(utilities.logging.PREFECT_LOG_RECORD_ATTRIBUTES) - set(
                items.keys()
            )
            for key in not_expected:
                assert key not in record.__dict__.keys()

    test_filter = DummyFilter()
    logger = logging.getLogger("prefect")
    logger.addFilter(test_filter)

    with context(items):
        logger.info("log entry!")

    logger.filters.pop()

    assert test_filter.called


def test_extra_loggers():
    with utilities.configuration.set_temporary_config(
        {"logging.extra_loggers": ["extra_logger"]}
    ):
        utilities.logging.configure_extra_loggers()
        assert (
            type(logging.root.manager.loggerDict.get("extra_logger")) == logging.Logger
        )
