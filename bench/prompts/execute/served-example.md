Programs are synchronous: write `function main()`, never `async`, `await` or `Promise`. Every call, a package's included, returns its value directly. Import every function and type you use from its package (`@scope/name`) or standard-library module (`submilli:…`); only built-ins need no import.

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

{served}
