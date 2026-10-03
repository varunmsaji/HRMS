"""Upper bounds shared by request schemas, sized to the database column types so an absurd client
value is a 422 at the edge rather than a driver-level overflow deep inside a write."""

#: Money in minor units is stored as BIGINT. 10**13 minor units is 10**11 major units — far beyond
#: any real salary, comfortably inside int64.
MAX_MONEY_MINOR = 10**13

#: Postgres INTEGER.
MAX_INT32 = 2_147_483_647

#: Largest JSON document a free-form `custom_fields` bag may serialise to.
MAX_CUSTOM_FIELDS_BYTES = 64 * 1024
