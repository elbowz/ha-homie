

HomieDevices[device_id] = HomieDevice()

HomieMessages[string] = string



class HomieDevice (device_id, parent_base)

    device_id
      -> device_id

    topic_base
      -> parent_base + / + device_id
    name
      -> topic_base + / + $name
    conventionVersion
      -> topic_base + / + $homie
    state
      -> topic_base + / + $online
    ip
      -> topic_base + / + $ip
    mac
      -> topic_base + / + $mac

    nodes[] (HomieNode)
      -> $nodes


    uptime
      -> topic_base + / + $stats/uptime
    signal
      -> topic_base + / + $stats/signal
    statsInterval
      -> topic_base + / + $stats/interval


    fw_name
      -> topic_base + / + $fw/name
    fw_version
      -> topic_base + / + $fw/version
    fw_checksum
      -> topic_base + / + $fw/checksum






class HomieNode(node_id, parent_base)

    node_id
      -> node_id

    topic_base
      -> parent_base + / + node_id 

    type
      -> topic_base + / + $type

    name
      -> topic_base + / + $name

    properties[] (HomieProperty)
      -> $properties



class HomieProperty (property_id, parent_base)

    
    property_id
      -> property_id

    topic_base
      -> parent_base + / + property_id

    settable
      -> topic_base + / + $settable

    unit
      -> topic_base + / + $unit

    $datatype
      -> topic_base + / + $datatype

    $name
      -> topic_base + / + $name

    $format
      -> topic_base + / + $format








