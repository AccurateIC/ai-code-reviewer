### JavaScript/TypeScript Specific Review Criteria

1. **Type Safety (TS)**
   - Avoid `any` type - use `unknown` if type is uncertain
   - Enable strict mode
   - Use interfaces over types for object shapes
   - Proper generic usage

2. **Async Patterns**
   - Prefer async/await over raw promises
   - Handle promise rejections
   - Use Promise.all for parallel operations
   - Avoid callback hell

3. **Memory Management**
   - Clean up event listeners
   - Avoid memory leaks in closures
   - Use WeakMap/WeakSet for cache with garbage collection
   - Clear intervals/timeouts

4. **Security**
   - Prevent XSS: sanitize user input
   - Use DOMPurify for HTML sanitization
   - Validate all API inputs
   - Use CSP headers

5. **Performance**
   - Debounce/Throttle expensive operations
   - Use memoization for pure functions
   - Lazy load components
   - Optimize re-renders (React)

6. **Modern JS**
   - Use const/let, never var
   - Use destructuring
   - Use spread operator appropriately
   - Use optional chaining (?.)
