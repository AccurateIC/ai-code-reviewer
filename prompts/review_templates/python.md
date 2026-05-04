### Python Specific Review Criteria

1. **Type Hints**
   - All function parameters should have type annotations
   - Return types should be specified
   - Use `typing` module for complex types (Optional, List, Dict, etc.)

2. **Docstrings**
   - All public functions must have docstrings
   - Follow Google or NumPy style
   - Include Args, Returns, Raises sections

3. **Error Handling**
   - Never use bare `except:` clauses
   - Catch specific exceptions
   - Use `try-except-finally` for resource cleanup
   - Consider using `contextlib.suppress` for expected exceptions

4. **Performance**
   - Use list comprehensions over map/filter
   - Use generators for large datasets
   - Avoid string concatenation in loops (use join)
   - Use `with` statements for file handling

5. **Security**
   - Use parameterized queries (never f-strings for SQL)
   - Validate all inputs
   - Use `secrets` module for cryptographic operations
   - Never log sensitive data

6. **Async/Await**
   - Use `asyncio` appropriately
   - Don't block the event loop
   - Use `aiohttp` for HTTP requests in async code
   - Properly await coroutines

7. **Imports**
   - Group imports: stdlib, third-party, local
   - Use absolute imports over relative
   - Remove unused imports
