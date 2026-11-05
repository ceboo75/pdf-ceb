from pdfceb import selftest


def test_all_operations(tmp_path):
    results = selftest.run(tmp_path)
    failed = [(n, m) for n, ok, m in results if not ok]
    assert not failed, failed
