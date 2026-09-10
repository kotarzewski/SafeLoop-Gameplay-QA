extends SceneTree

var spec: Dictionary = {}
var scene_root: Node = null
var out_path: String = ""
var samples: Array = []
var missing_watch_nodes: Array[String] = []
var missing_input_actions: Array[String] = []
var active_actions: Dictionary = {}

func _initialize() -> void:
    call_deferred("_run")

func _arg_value(prefix: String) -> String:
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with(prefix):
            return arg.substr(prefix.length())
    return ""

func _read_json(path: String) -> Variant:
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return null
    return JSON.parse_string(file.get_as_text())

func _write_json(path: String, value: Variant) -> bool:
    var file := FileAccess.open(path, FileAccess.WRITE)
    if file == null:
        return false
    file.store_string(JSON.stringify(value))
    return true

func _fail(message: String) -> void:
    if out_path != "":
        _write_json(out_path, {"ok": false, "error": message, "samples": samples})
    push_error("SAFELOOP_QA: " + message)
    quit(2)

func _run() -> void:
    var spec_path := _arg_value("--qa-spec=")
    out_path = _arg_value("--qa-out=")
    if spec_path == "" or out_path == "":
        _fail("Missing --qa-spec or --qa-out")
        return
    var loaded := _read_json(spec_path)
    if not (loaded is Dictionary):
        _fail("Invalid QA spec JSON")
        return
    spec = loaded

    var scene_path := String(spec.get("scene", ""))
    if scene_path == "":
        scene_path = String(ProjectSettings.get_setting("application/run/main_scene", ""))
    if scene_path == "":
        _fail("No scene specified and application/run/main_scene is empty")
        return
    if not scene_path.begins_with("res://"):
        scene_path = "res://" + scene_path.trim_prefix("./")

    var packed := load(scene_path)
    if packed == null or not (packed is PackedScene):
        _fail("Could not load scene: " + scene_path)
        return
    scene_root = packed.instantiate()
    root.add_child(scene_root)

    var physics_fps := int(spec.get("physics_fps", 60))
    Engine.physics_ticks_per_second = physics_fps
    var sample_hz := int(spec.get("sample_hz", min(60, physics_fps)))
    var sample_every := max(1, int(round(float(physics_fps) / float(sample_hz))))
    var duration_s := float(spec.get("duration_s", 5.0))
    var total_frames := int(ceil(duration_s * physics_fps))

    await process_frame
    await physics_frame

    for frame in range(total_frames + 1):
        var t := float(frame) / float(physics_fps)
        _apply_inputs(t)
        if frame % sample_every == 0:
            _sample(t)
        if frame < total_frames:
            await physics_frame

    _release_all_actions()

    var grounding_result: Variant = null
    var grounding := spec.get("grounding")
    if grounding is Dictionary and bool(grounding.get("enabled", true)):
        grounding_result = _scan_ground_support(grounding)

    var result := {
        "ok": true,
        "spec": spec,
        "samples": samples,
        "missing_watch_nodes": missing_watch_nodes,
        "missing_input_actions": missing_input_actions,
        "grounding": grounding_result,
    }
    if not _write_json(out_path, result):
        push_error("SAFELOOP_QA: Failed writing result")
        quit(3)
        return
    quit(0)

func _apply_inputs(t: float) -> void:
    var desired: Dictionary = {}
    for item in spec.get("inputs", []):
        if not (item is Dictionary):
            continue
        var action := String(item.get("action", ""))
        var start_s := float(item.get("start_s", 0.0))
        var end_s := float(item.get("end_s", 0.0))
        if t >= start_s and t < end_s:
            desired[action] = max(float(desired.get(action, 0.0)), float(item.get("strength", 1.0)))

    for action in desired.keys():
        if not InputMap.has_action(action):
            if not missing_input_actions.has(action):
                missing_input_actions.append(action)
            continue
        var strength := float(desired[action])
        var previous_strength := float(active_actions.get(action, -1.0))
        Input.action_press(action, strength)
        if previous_strength < 0.0 or abs(previous_strength - strength) > 0.0001:
            _emit_action_event(action, true, strength)
        active_actions[action] = strength

    for action in active_actions.keys().duplicate():
        if not desired.has(action):
            Input.action_release(action)
            _emit_action_event(action, false, 0.0)
            active_actions.erase(action)

func _emit_action_event(action: StringName, pressed: bool, strength: float) -> void:
    var event := InputEventAction.new()
    event.action = action
    event.pressed = pressed
    event.strength = strength if pressed else 0.0
    Input.parse_input_event(event)

func _release_all_actions() -> void:
    for action in active_actions.keys():
        Input.action_release(action)
        _emit_action_event(action, false, 0.0)
    active_actions.clear()

func _resolve_watch(path_text: String) -> Node:
    if path_text.begins_with("/root/"):
        return root.get_node_or_null(NodePath(path_text.trim_prefix("/root/")))
    return scene_root.get_node_or_null(NodePath(path_text))

func _serializable_property(value: Variant) -> Variant:
    if value is Vector2:
        return [value.x, value.y]
    if value is Vector3:
        return [value.x, value.y, value.z]
    if value is Quaternion:
        return [value.x, value.y, value.z, value.w]
    if value is Transform3D:
        return null
    var kind := typeof(value)
    if kind == TYPE_FLOAT or kind == TYPE_INT or kind == TYPE_BOOL or kind == TYPE_STRING:
        return value
    return null

func _sample(t: float) -> void:
    for watch in spec.get("watch", []):
        if not (watch is Dictionary):
            continue
        var wid := String(watch.get("id", "node"))
        var path_text := String(watch.get("node_path", ""))
        var node := _resolve_watch(path_text)
        if node == null:
            if not missing_watch_nodes.has(path_text):
                missing_watch_nodes.append(path_text)
            continue
        var row := {"t": t, "id": wid, "node_path": path_text}
        if node is Node3D:
            var n3 := node as Node3D
            var pos := n3.global_position
            var rot := n3.global_rotation_degrees
            var forward := -n3.global_transform.basis.z.normalized()
            row["position"] = [pos.x, pos.y, pos.z]
            row["rotation_deg"] = [rot.x, rot.y, rot.z]
            row["forward"] = [forward.x, forward.y, forward.z]
        if node is RigidBody3D:
            var rigid := node as RigidBody3D
            var vel := rigid.linear_velocity
            var ang := rigid.angular_velocity
            row["velocity"] = [vel.x, vel.y, vel.z]
            row["angular_velocity"] = [ang.x, ang.y, ang.z]
            row["sleeping"] = rigid.sleeping
        elif node is CharacterBody3D:
            var character := node as CharacterBody3D
            var cvel := character.velocity
            row["velocity"] = [cvel.x, cvel.y, cvel.z]
            row["on_floor"] = character.is_on_floor()

        var props: Dictionary = {}
        for prop_name in watch.get("properties", []):
            var value = node.get(String(prop_name))
            var serial = _serializable_property(value)
            if serial != null:
                props[String(prop_name)] = serial
        if not props.is_empty():
            row["props"] = props
        samples.append(row)

func _collect_nodes(node: Node, out: Array[Node]) -> void:
    out.append(node)
    for child in node.get_children():
        _collect_nodes(child, out)

func _first_mesh(node: Node) -> MeshInstance3D:
    if node is MeshInstance3D:
        return node as MeshInstance3D
    for child in node.get_children():
        var found := _first_mesh(child)
        if found != null:
            return found
    return null

func _collect_collision_rids(node: Node, out: Array[RID]) -> void:
    if node is CollisionObject3D:
        out.append((node as CollisionObject3D).get_rid())
    for child in node.get_children():
        _collect_collision_rids(child, out)


func _collect_ancestor_collision_rids(node: Node, out: Array[RID]) -> void:
    var current := node.get_parent()
    while current != null and current != scene_root.get_parent():
        if current is CollisionObject3D:
            var rid := (current as CollisionObject3D).get_rid()
            if not out.has(rid):
                out.append(rid)
        if current == scene_root:
            break
        current = current.get_parent()

func _mesh_bottom_center(mesh: MeshInstance3D) -> Vector3:
    var aabb := mesh.get_aabb()
    var p := aabb.position
    var s := aabb.size
    var corners := [
        Vector3(p.x, p.y, p.z),
        Vector3(p.x + s.x, p.y, p.z),
        Vector3(p.x, p.y, p.z + s.z),
        Vector3(p.x + s.x, p.y, p.z + s.z),
        Vector3(p.x, p.y + s.y, p.z),
        Vector3(p.x + s.x, p.y + s.y, p.z),
        Vector3(p.x, p.y + s.y, p.z + s.z),
        Vector3(p.x + s.x, p.y + s.y, p.z + s.z),
    ]
    var min_y := INF
    var min_x := INF
    var max_x := -INF
    var min_z := INF
    var max_z := -INF
    for corner in corners:
        var world := mesh.global_transform * corner
        min_y = min(min_y, world.y)
        min_x = min(min_x, world.x)
        max_x = max(max_x, world.x)
        min_z = min(min_z, world.z)
        max_z = max(max_z, world.z)
    return Vector3((min_x + max_x) * 0.5, min_y, (min_z + max_z) * 0.5)

func _ignored_path(path_text: String, prefixes: Array) -> bool:
    for prefix in prefixes:
        if path_text.begins_with(String(prefix)):
            return true
    return false

func _scan_ground_support(cfg: Dictionary) -> Dictionary:
    var all_nodes: Array[Node] = []
    _collect_nodes(scene_root, all_nodes)
    var candidates: Array[Node] = []
    var mode := String(cfg.get("mode", "rigid_and_group"))
    var group_name := String(cfg.get("group", "safeloop_grounded"))
    var ignore_prefixes: Array = cfg.get("ignore_path_prefixes", [])

    for node in all_nodes:
        var path_text := String(scene_root.get_path_to(node))
        if _ignored_path(path_text, ignore_prefixes):
            continue
        var include := false
        if mode == "strict_group":
            include = node.is_in_group(group_name)
        elif mode == "heuristic_all_meshes":
            include = node is MeshInstance3D
        else:
            include = node.is_in_group(group_name) or node is RigidBody3D
        if include and node is Node3D:
            candidates.append(node)

    var results: Array = []
    var max_gap := float(cfg.get("max_gap_m", 0.08))
    var ray_length := float(cfg.get("ray_length_m", 3.0))
    var max_vy := float(cfg.get("max_vertical_speed_mps", 0.15))

    for candidate in candidates:
        var mesh := _first_mesh(candidate)
        if mesh == null:
            results.append({
                "path": String(scene_root.get_path_to(candidate)),
                "status": "no_mesh_for_bottom_estimate",
                "supported": false,
                "confidence": "low",
            })
            continue
        var bottom := _mesh_bottom_center(mesh)
        var from := bottom + Vector3.UP * 0.02
        var to := bottom + Vector3.DOWN * ray_length
        var query := PhysicsRayQueryParameters3D.create(from, to)
        var excluded: Array[RID] = []
        _collect_collision_rids(candidate, excluded)
        _collect_ancestor_collision_rids(candidate, excluded)
        query.exclude = excluded
        query.collide_with_areas = false
        query.collide_with_bodies = true
        var hit := (candidate as Node3D).get_world_3d().direct_space_state.intersect_ray(query)
        var gap: Variant = null
        var has_support := not hit.is_empty()
        if has_support:
            gap = max(0.0, bottom.y - (hit["position"] as Vector3).y)
        var vertical_speed := 0.0
        if candidate is RigidBody3D:
            vertical_speed = abs((candidate as RigidBody3D).linear_velocity.y)
        var supported := has_support and float(gap) <= max_gap and vertical_speed <= max_vy
        var status := "supported" if supported else ("no_support_ray_hit" if not has_support else ("gap_exceeds_limit" if float(gap) > max_gap else "vertical_motion_exceeds_limit"))
        results.append({
            "path": String(scene_root.get_path_to(candidate)),
            "status": status,
            "supported": supported,
            "gap_m": gap,
            "vertical_speed_mps": vertical_speed,
            "max_gap_m": max_gap,
            "confidence": "heuristic" if mode == "heuristic_all_meshes" else "targeted",
        })

    return {
        "mode": mode,
        "candidate_count": results.size(),
        "unsupported_count": results.filter(func(item): return not bool(item.get("supported", false))).size(),
        "results": results,
        "note": "heuristic_all_meshes can intentionally flag floors, suspended props, decorative geometry or meshes whose collision is represented elsewhere; strict_group is authoritative only for nodes deliberately marked as expected-grounded.",
    }
