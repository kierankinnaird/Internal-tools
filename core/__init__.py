"""The small contract between a module and whatever hosts it.

A module only ever talks to the host through 'Context' (who is the user, what may they do, write an audit entry) and 'Module' (what the module is called and what it adds to the mednu). Nothing in a module imports from a host."""