from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NavigationStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NAVIGATION_STATUS_UNSPECIFIED: _ClassVar[NavigationStatus]
    NAVIGATION_STATUS_ATRACADO: _ClassVar[NavigationStatus]
    NAVIGATION_STATUS_EM_TRAVESSIA: _ClassVar[NavigationStatus]
    NAVIGATION_STATUS_MANOBRA: _ClassVar[NavigationStatus]
    NAVIGATION_STATUS_EMERGENCIA: _ClassVar[NavigationStatus]

class LinkType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    LINK_TYPE_UNSPECIFIED: _ClassVar[LinkType]
    LINK_TYPE_RADIO_VHF_MARITIMO: _ClassVar[LinkType]
    LINK_TYPE_4G_5G_COSTEIRO: _ClassVar[LinkType]
    LINK_TYPE_SATELITAL: _ClassVar[LinkType]
    LINK_TYPE_WIFI_TERMINAL: _ClassVar[LinkType]

class AckStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACK_STATUS_UNSPECIFIED: _ClassVar[AckStatus]
    ACK_STATUS_ACEITO: _ClassVar[AckStatus]
    ACK_STATUS_DUPLICADO_IGNORADO: _ClassVar[AckStatus]
    ACK_STATUS_REJEITADO: _ClassVar[AckStatus]
NAVIGATION_STATUS_UNSPECIFIED: NavigationStatus
NAVIGATION_STATUS_ATRACADO: NavigationStatus
NAVIGATION_STATUS_EM_TRAVESSIA: NavigationStatus
NAVIGATION_STATUS_MANOBRA: NavigationStatus
NAVIGATION_STATUS_EMERGENCIA: NavigationStatus
LINK_TYPE_UNSPECIFIED: LinkType
LINK_TYPE_RADIO_VHF_MARITIMO: LinkType
LINK_TYPE_4G_5G_COSTEIRO: LinkType
LINK_TYPE_SATELITAL: LinkType
LINK_TYPE_WIFI_TERMINAL: LinkType
ACK_STATUS_UNSPECIFIED: AckStatus
ACK_STATUS_ACEITO: AckStatus
ACK_STATUS_DUPLICADO_IGNORADO: AckStatus
ACK_STATUS_REJEITADO: AckStatus

class NavigationData(_message.Message):
    __slots__ = ("latitude", "longitude", "velocidade_nos", "rumo_graus", "status_navegacao")
    LATITUDE_FIELD_NUMBER: _ClassVar[int]
    LONGITUDE_FIELD_NUMBER: _ClassVar[int]
    VELOCIDADE_NOS_FIELD_NUMBER: _ClassVar[int]
    RUMO_GRAUS_FIELD_NUMBER: _ClassVar[int]
    STATUS_NAVEGACAO_FIELD_NUMBER: _ClassVar[int]
    latitude: float
    longitude: float
    velocidade_nos: float
    rumo_graus: float
    status_navegacao: NavigationStatus
    def __init__(self, latitude: _Optional[float] = ..., longitude: _Optional[float] = ..., velocidade_nos: _Optional[float] = ..., rumo_graus: _Optional[float] = ..., status_navegacao: _Optional[_Union[NavigationStatus, str]] = ...) -> None: ...

class PropulsionData(_message.Message):
    __slots__ = ("rpm_motor", "temperatura_motor_celsius", "pressao_oleo_bar", "nivel_combustivel_percentual", "consumo_instantaneo_lph")
    RPM_MOTOR_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURA_MOTOR_CELSIUS_FIELD_NUMBER: _ClassVar[int]
    PRESSAO_OLEO_BAR_FIELD_NUMBER: _ClassVar[int]
    NIVEL_COMBUSTIVEL_PERCENTUAL_FIELD_NUMBER: _ClassVar[int]
    CONSUMO_INSTANTANEO_LPH_FIELD_NUMBER: _ClassVar[int]
    rpm_motor: float
    temperatura_motor_celsius: float
    pressao_oleo_bar: float
    nivel_combustivel_percentual: float
    consumo_instantaneo_lph: float
    def __init__(self, rpm_motor: _Optional[float] = ..., temperatura_motor_celsius: _Optional[float] = ..., pressao_oleo_bar: _Optional[float] = ..., nivel_combustivel_percentual: _Optional[float] = ..., consumo_instantaneo_lph: _Optional[float] = ...) -> None: ...

class NetworkDiagnostics(_message.Message):
    __slots__ = ("rssi_dbm", "latencia_rtt_ms", "perda_pacotes_percentual", "tamanho_buffer_local", "tentativa_envio", "tipo_enlace")
    RSSI_DBM_FIELD_NUMBER: _ClassVar[int]
    LATENCIA_RTT_MS_FIELD_NUMBER: _ClassVar[int]
    PERDA_PACOTES_PERCENTUAL_FIELD_NUMBER: _ClassVar[int]
    TAMANHO_BUFFER_LOCAL_FIELD_NUMBER: _ClassVar[int]
    TENTATIVA_ENVIO_FIELD_NUMBER: _ClassVar[int]
    TIPO_ENLACE_FIELD_NUMBER: _ClassVar[int]
    rssi_dbm: int
    latencia_rtt_ms: float
    perda_pacotes_percentual: float
    tamanho_buffer_local: int
    tentativa_envio: int
    tipo_enlace: LinkType
    def __init__(self, rssi_dbm: _Optional[int] = ..., latencia_rtt_ms: _Optional[float] = ..., perda_pacotes_percentual: _Optional[float] = ..., tamanho_buffer_local: _Optional[int] = ..., tentativa_envio: _Optional[int] = ..., tipo_enlace: _Optional[_Union[LinkType, str]] = ...) -> None: ...

class TelemetryPacket(_message.Message):
    __slots__ = ("message_id", "boat_id", "timestamp_coleta", "passageiros", "navegacao", "propulsao", "rede")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    BOAT_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_COLETA_FIELD_NUMBER: _ClassVar[int]
    PASSAGEIROS_FIELD_NUMBER: _ClassVar[int]
    NAVEGACAO_FIELD_NUMBER: _ClassVar[int]
    PROPULSAO_FIELD_NUMBER: _ClassVar[int]
    REDE_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    boat_id: str
    timestamp_coleta: int
    passageiros: int
    navegacao: NavigationData
    propulsao: PropulsionData
    rede: NetworkDiagnostics
    def __init__(self, message_id: _Optional[str] = ..., boat_id: _Optional[str] = ..., timestamp_coleta: _Optional[int] = ..., passageiros: _Optional[int] = ..., navegacao: _Optional[_Union[NavigationData, _Mapping]] = ..., propulsao: _Optional[_Union[PropulsionData, _Mapping]] = ..., rede: _Optional[_Union[NetworkDiagnostics, _Mapping]] = ...) -> None: ...

class TelemetryAck(_message.Message):
    __slots__ = ("message_id", "sucesso", "duplicado", "processado_em", "mensagem", "status")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SUCESSO_FIELD_NUMBER: _ClassVar[int]
    DUPLICADO_FIELD_NUMBER: _ClassVar[int]
    PROCESSADO_EM_FIELD_NUMBER: _ClassVar[int]
    MENSAGEM_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    sucesso: bool
    duplicado: bool
    processado_em: int
    mensagem: str
    status: AckStatus
    def __init__(self, message_id: _Optional[str] = ..., sucesso: _Optional[bool] = ..., duplicado: _Optional[bool] = ..., processado_em: _Optional[int] = ..., mensagem: _Optional[str] = ..., status: _Optional[_Union[AckStatus, str]] = ...) -> None: ...
