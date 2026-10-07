def pytest_configure(config):
    config.addinivalue_line("markers", "docker: needs a local Docker daemon (builds images, runs containers)")
