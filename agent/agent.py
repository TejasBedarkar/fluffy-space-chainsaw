import asyncio
import logging
import os
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# --- 1. SETUP PATHS ---
CURRENT_DIR = Path(__file__).parent.absolute()
PARENT_DIR = CURRENT_DIR.parent
sys.path.append(str(PARENT_DIR))

# Load .env from parent directory (where keys are stored)
if (CURRENT_DIR / ".env").exists():
    load_dotenv(CURRENT_DIR / ".env")
elif (PARENT_DIR / ".env").exists():
    load_dotenv(PARENT_DIR / ".env")

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.agents.voice import VoiceActivityVideoSampler, room_io
from livekit.plugins import anam, google

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ppt-agent")

# --- 2. SUPABASE SETUP ---
# Initialize the client to fetch data from your cloud database
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("❌ Critical: SUPABASE_URL or SUPABASE_KEY is missing from environment variables.")
    # We don't exit here to allow the agent to start and report the error via logs, 
    # but actual functionality will fail.
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

last_slide_time = 0

# --- 3. FETCH DATA FROM DB ---
def fetch_latest_presentation():
    """
    Queries Supabase for the most recently created presentation 
    and returns its slide data.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None, []

    try:
        # A. Get the latest Presentation ID
        # We assume the 'created_at' column exists as per your schema
        response = supabase.table("presentations") \
            .select("id") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        if not response.data:
            logger.warning("⚠️ No presentations found in the database.")
            return None, []

        presentation_id = response.data[0]['id']
        logger.info(f"📚 Found latest Presentation ID: {presentation_id}")

        # B. Get all Slides for this Presentation
        # Ordered by slide_number so the Agent reads them in order
        slides_response = supabase.table("slides") \
            .select("*") \
            .eq("presentation_id", presentation_id) \
            .order("slide_number", desc=False) \
            .execute()
            
        slides = slides_response.data
        logger.info(f"✅ Loaded {len(slides)} slides from Database.")
        return presentation_id, slides

    except Exception as e:
        logger.error(f"❌ Database Error: {e}")
        return None, []

# --- 4. BUILD PROMPT ---
def build_instructions():
    # Fetch real data from Supabase
    pid, slides = fetch_latest_presentation()
    
    if slides:
        slide_count = len(slides)
        
        # Format the context for the AI
        # We convert the list of dicts into a clean string representation
        content_context = ""
        for slide in slides:
            # Assuming columns: slide_number, content
            content_context += f"[Slide {slide['slide_number']}]: {slide.get('content', '')}\n"

        intro = f"Namaste! I have loaded the latest presentation from the database with {slide_count} slides. I am ready. Shall I start?"
        source_material = f"### SLIDE CONTENT (READ FROM DATABASE):\n{content_context}"
    else:
        intro = "Namaste! I cannot find any presentations in the database. Please upload one via the dashboard."
        source_material = "No presentation content available."
        slide_count = 0
        slides = [] # Empty list to prevent errors

    instructions = f"""
    You are **Dia**, a professional Indian Presentation Assistant.

    {source_material}
    
    **TOTAL SLIDES:** {slide_count}

    ### YOUR STRICT BEHAVIOR LOOP:
    1.  **EXPLAIN:** Explain the current slide in **MAX 2 SENTENCES**. Brief explanations prevent errors.
    2.  **CHECK PROGRESS:**
        - **IF** this is NOT the last slide (Slide Number < {slide_count}):
            - Ask exactly: **"Shall I move to the next slide?"**
            - **STOP TALKING.** Wait for the user to say "Yes".
            - When user says "Yes", call `update_slide(current + 1)`.
        - **IF** this IS the last slide (Slide Number == {slide_count}):
            - Say exactly: **"That concludes the presentation. Do you have any questions?"**
            - **STOP TALKING.** Wait for questions.

    ### RULES:
    - Never change slides without confirmation.
    - Keep it short.
    """
    
    # Return slides list too, so the tool can access image_urls later
    return instructions, intro, slides

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 Connecting to room: {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    try:
        # Load API Keys
        anam_api_key = os.environ.get("ANAM_API_KEY")
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        avatar_id = os.environ.get("ANAM_AVATAR_ID")

        if not all([anam_api_key, gemini_api_key, avatar_id]):
            logger.error("❌ Missing AI API Keys (ANAM or GEMINI)")
            return

        # Build instructions using DB data
        instructions_text, greeting_text, slides_data = build_instructions()

        # --- 5. TOOL DEFINITION ---
        @function_tool
        async def update_slide(slide_number: int):
            """Change the visible slide."""
            global last_slide_time
            current_time = time.time()
            
            if current_time - last_slide_time < 2:
                return f"Slide {slide_number} is already active (Debounced)."
            
            last_slide_time = current_time
            
            # Find the correct URL from our loaded slides_data
            # Slides are 1-indexed, Python lists are 0-indexed
            target_url = None
            if 0 < slide_number <= len(slides_data):
                # Safe access
                slide_info = slides_data[slide_number - 1]
                target_url = slide_info.get('image_url')
            
            if not target_url:
                logger.warning(f"⚠️ Requested Slide {slide_number} not found in data.")
                return f"Error: Slide {slide_number} does not exist."

            logger.info(f"📸 SWITCHING TO SLIDE {slide_number} -> URL: {target_url}")
            
            # Send signal to Frontend
            # The Frontend will receive this URL and set it as the <img> src
            for _ in range(2):
                data = json.dumps({
                    "type": "slide_change", 
                    "slide_number": slide_number,
                    "image_url": target_url  # This is now a full Supabase URL
                })
                try:
                    await ctx.room.local_participant.publish_data(payload=data, reliable=True)
                except Exception as e:
                    logger.warning(f"Failed to publish slide update: {e}")
                await asyncio.sleep(0.1)

            return f"Screen updated to Slide {slide_number}"

        # Initialize Model
        llm_model = google.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-09-2025", 
            api_key=gemini_api_key,
            voice="Aoede", 
            instructions=instructions_text,
            temperature=0.6,
        )

        avatar = anam.AvatarSession(
            persona_config=anam.PersonaConfig(name="Presenter", avatarId=avatar_id),
            api_key=anam_api_key,
            api_url="https://api.anam.ai",
        )

        session = AgentSession(
            llm=llm_model,
            video_sampler=VoiceActivityVideoSampler(speaking_fps=0, silent_fps=0),
            preemptive_generation=False, 
        )

        try:
            await avatar.start(session, room=ctx.room)
            
            await session.start(
                agent=Agent(
                    instructions=instructions_text,
                    tools=[update_slide]
                ),
                room=ctx.room,
                room_input_options=room_io.RoomInputOptions(video_enabled=True),
            )

            session.generate_reply(instructions=f"Say exactly: '{greeting_text}'")
            logger.info("✅ Agent Active")

            # Universal Keep-Alive
            shutdown_future = asyncio.Future()
            @ctx.room.on("disconnected")
            def on_disconnected(reason):
                if not shutdown_future.done():
                    shutdown_future.set_result(None)
            
            await shutdown_future

        except Exception as inner_e:
            err_str = str(inner_e)
            if "RpcError" in err_str or "ChanClosed" in err_str or "Connection timeout" in err_str:
                logger.warning(f"⚠️ Network Glitch Ignored: {inner_e}")
            else:
                logger.error(f"⚠️ Session Error: {inner_e}")

    except Exception as e:
        logger.error(f"❌ Critical Error: {e}", exc_info=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))