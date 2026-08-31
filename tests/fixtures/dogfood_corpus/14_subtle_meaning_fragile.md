# Security Vulnerability Disclosure

The identified vulnerability allows unauthorized read access to session tokens under specific race conditions when response caching is enabled in the reverse proxy. It does not permit arbitrary code execution, nor does it allow write access to database records.
