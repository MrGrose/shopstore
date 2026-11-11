class GatewayError(Exception):
    pass


class GatewayAuthError(GatewayError):
    pass


class GatewayDeliveryError(GatewayError):
    pass


class GatewayVerificationError(GatewayError):
    pass
