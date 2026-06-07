from robot_mcp_server.parser import RobotResultParser


def test_parse_run_summary():
    parser = RobotResultParser()
    summary = parser.parse_run("examples/sample_output.xml")

    assert summary.total == 3
    assert summary.failed == 2
    assert summary.passed == 1
    assert summary.skipped == 0
    assert summary.source_path.endswith("examples/sample_output.xml")


def test_get_failed_tests():
    parser = RobotResultParser()
    parser.parse_run("examples/sample_output.xml")
    failed = parser.get_failed_tests()

    assert len(failed) == 2
    names = {test.test_name for test in failed}
    assert "Failing Test" in names
    assert "New Failure Test" in names


def test_get_test_details():
    parser = RobotResultParser()
    parser.parse_run("examples/sample_output.xml")
    details = parser.get_test_details("Failing Test")

    assert details.status == "FAIL"
    assert "Expected 42 but got 43" in details.message
    assert details.failed_keyword == "Verify Result"
    assert len(details.keyword_trace) >= 2


def test_missing_file_raises_file_not_found():
    parser = RobotResultParser()
    try:
        parser.parse_run("examples/missing_output.xml")
        assert False, "Expected FileNotFoundError for missing file"
    except FileNotFoundError:
        pass


def test_invalid_test_name_raises_value_error():
    parser = RobotResultParser()
    parser.parse_run("examples/sample_output.xml")
    try:
        parser.get_test_details("Does Not Exist")
        assert False, "Expected ValueError when test name is not found"
    except ValueError:
        pass
