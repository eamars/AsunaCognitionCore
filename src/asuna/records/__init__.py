"""The owners of the collections read across many domains: one module per collection, the only code that names its
fields and builds its conditions (ADR-104). Each takes a store (anything with `collection(name)`) as its first
argument; a call site calls the owner's named operations and never sees a condition."""
