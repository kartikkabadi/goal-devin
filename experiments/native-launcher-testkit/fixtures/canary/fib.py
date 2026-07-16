def fib(n):
    """Return the nth Fibonacci number."""
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
