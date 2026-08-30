"""Pytest configuration — suppress known warnings."""
import warnings

# Suppress pynvml deprecation warning during tests
warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
