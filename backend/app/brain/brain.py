import logging
from typing import Dict, Any, Tuple, Optional
from app.context.engine import context_engine
from app.providers.router import ai_router
from app.tools.registry import tool_registry
from app.planner.planner import agent_planner
from app.events.bus import event_bus, SystemEvent

logger = logging.getLogger("holmev.brain")

class HolmevBrain:
    async def process_user_request(self, user_input: str, session_id: str = "default_session", user_emotion: str = "NEUTRAL") -> Dict[str, Any]:
        """
        Master Intelligence Pipeline:
        User Input -> Context Engine -> AI Provider Router -> Planner -> Permission Check -> Tool Execution -> Spoken Response
        """
        # 1. Update Context
        context_engine.update_context(user_input, role="user")
        curr_context = context_engine.get_full_context()

        # Emit thinking event
        await event_bus.emit(SystemEvent(
            event_type="AI_THINKING",
            source="brain",
            session_id=session_id,
            payload={"input": user_input, "emotion": user_emotion}
        ))

        # 2. Intent Understanding & Structured Tool Mapping
        available_tools = tool_registry.list_tools()
        tool_plan_spec = await ai_router.generate_tool_plan(user_input, available_tools, curr_context)

        tool_name = tool_plan_spec.get("tool")
        arguments = tool_plan_spec.get("arguments", {})

        # Emit tool started event
        await event_bus.emit(SystemEvent(
            event_type="TOOL_STARTED",
            source="brain",
            session_id=session_id,
            payload={"tool": tool_name, "arguments": arguments}
        ))

        # 3. Plan & Execute Tool via Planner & Permission Engine
        plan, result = await agent_planner.create_and_execute_plan(user_query=user_input, plan_spec=tool_plan_spec)

        # 4. Formulate verified friendly response based on emotion & tool execution
        spoken_response = self._formulate_speech_response(user_input, tool_name or "", arguments, result, user_emotion)

        context_engine.update_context(spoken_response, role="assistant")

        # Emit completion event
        event_type = "TOOL_COMPLETED" if result.get("success") else "TOOL_FAILED"
        await event_bus.emit(SystemEvent(
            event_type=event_type,
            source="brain",
            session_id=session_id,
            payload={"result": result, "spoken_response": spoken_response}
        ))

        return {
            "query": user_input,
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
            "plan_status": plan.status,
            "spoken_response": spoken_response
        }

    def _formulate_speech_response(self, query: str, tool_name: Optional[str], args: Dict[str, Any], result: Dict[str, Any], emotion: str = "NEUTRAL") -> str:
        if not result.get("success"):
            err = result.get("error", "Task execution failed.")
            return f"Boss, {err}"

        data = result.get("data", {})

        if tool_name == "home.cctv.show":
            if data.get("action_required") == "DISAMBIGUATION_NEEDED":
                return data.get("question", "Konsa wala CCTV camera dikhaoon?")
            return data.get("message", "CCTV feed display kar di gayi hai.")

        if tool_name == "home.ir.learn":
            return data.get("message", "IR receiver ready hai. Physical remote ka button press karein.")

        if tool_name == "navigation.get_route":
            if data.get("spoken_response"):
                return data["spoken_response"]
            return f"{args.get('destination', 'Destination')} ka route navigation layout display kar diya hai."

        if tool_name == "mobile.whatsapp.send":
            return data.get("spoken_response", "WhatsApp message send kar diya gaya hai.")

        if tool_name == "mobile.phone.call":
            return data.get("spoken_response", "Phone call initiate ho rahi hai.")

        if tool_name == "mobile.email.send":
            return data.get("spoken_response", "Email bhej di gayi hai.")

        if tool_name == "mobile.image.display":
            return data.get("spoken_response", "Mobile photo screen par display kar di gayi hai.")

        if tool_name == "desktop.system_control":
            return f"System {args.get('action', 'action')} schedule ho gaya hai, Boss."

        if tool_name == "desktop.open_application":
            return f"{args.get('application', 'Application').capitalize()} khol diya gaya hai, Boss."

        if tool_name == "browser.open":
            return f"Browser launch karke {args.get('url')} open kar diya gaya hai."

        if tool_name == "desktop.create_folder":
            return f"Folder {data.get('path')} successfully create ho gaya hai."

        if tool_name == "desktop.type_text":
            return f"Text successfully type kar diya gaya hai."

        if tool_name == "home.device.set_power":
            dev_name = data.get("device", "Device")
            power_str = "ON" if data.get("state", {}).get("power") else "OFF"
            speed_val = data.get("state", {}).get("speed")
            speed_str = f" speed {speed_val} par" if speed_val is not None else ""
            return f"{dev_name} {power_str}{speed_str} set kar diya gaya hai, Boss."

        if tool_name == "threed.create_object":
            return f"3D workspace mein {args.get('object_type', 'object')} primitive add ho gaya hai."

        if tool_name == "threed.transform_object":
            return "3D object transform update kar diya gaya hai."

        if tool_name == "circuit.create":
            sim = data.get("simulation", {})
            curr = sim.get("current_ma", 0)
            return f"LED circuit construct ho gaya hai. Current draw {curr} mA hai, circuit working condition mein hai."

        if tool_name == "memory.store":
            return f"Yeh baat memory mein store kar li gayi hai, Boss."

        if tool_name == "web.search":
            snippets = data.get("snippets", [])
            if snippets:
                return f"Search result: {snippets[0]}"
            return f"Web search complete ho gaya hai."

        return "Task complete ho gaya hai, Boss."

holmev_brain = HolmevBrain()
