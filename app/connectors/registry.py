CONNECTORS = {}


def register_connector(connector_class):
    """
    Register connector automatically.
    """

    CONNECTORS[
        connector_class.connector_name
    ] = connector_class

    return connector_class