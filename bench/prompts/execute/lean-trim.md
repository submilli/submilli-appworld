Run a Submilli program: a strict TypeScript subset, compiled to WebAssembly.

Before your first program, call `submilli__typescript__packages__docs` with every package and module you will import, and use those declarations rather than guessing APIs. `submilli__typescript__packages__search` finds packages, and `submilli__typescript__builtins__docs` declares the built-ins.

Programs are synchronous: write `function main()`, never `async`, `await` or `Promise`. Every call, a package's included, returns its value directly. Import every function and type you use from its package (`@scope/name`) or standard-library module (`submilli:url`, `submilli:crypto`, `submilli:uuid`). Built-ins need no import: `console`, Array, BigInt, Boolean, Error, Map, Number, Object, RangeError, Record, RegExp, Set, String, TextDecoder, TextEncoder, TypeError, Uint8Array, and the namespaces JSON, Math and Temporal (there is no `Date`).

```ts
import { list_orders, type Order } from "@shop/orders";

function main(): string[] {
    const large: Order[] = [];
    for (let page = 0; ; page++) {
        const orders = list_orders({ page_index: page });
        if (orders.length === 0) break;
        for (const order of orders) {
            if (order.total > 100) large.push(order);
        }
    }
    return large.map((order) => order.id);
}
```

There is no `any`: use the package's types, or `unknown` narrowed with `typeof`, `Array.isArray` or `===`. Function declarations need a return type. `x == null` is a compile error: write `x === null` or `x === undefined`.

Postfix `x!` is a runtime-checked non-null assertion: it removes `null` and `undefined` from the type and throws `TypeError` for either. Missing properties, collection misses, and omitted optional parameters use `undefined`; `null` is distinct. Defaults apply to omission or `undefined`, never `null`. Optional chains yield `undefined`; `??` handles both values. `arr[i]` out of range throws `RangeError`; probe with `arr.at(i)`, which returns `undefined`. `let x: T;` needs an initializer unless `T` includes `undefined`.
No runtime reflection: of `Object.prototype` only `.toString()` is available, so no `.hasOwnProperty()`. Narrow optional values with `obj.field !== undefined`; `"field" in obj` narrows `unknown` or unions distinguished by field presence. Use `Record<string, V>` for dynamic `obj[key]` reads and writes; a read's type is `V | undefined`.

Do the work in one program: follow pagination and data dependencies in code, filter and aggregate there, and return only what the answer or your next decision needs.

The output is what `main()` returns: a string as is, anything else as JSON. `console.log` goes to a separate debug stream, and a failed run returns the error with the console output.
