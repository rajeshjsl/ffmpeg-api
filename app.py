from flask import Flask, request, jsonify, send_file
import subprocess
import os
import uuid
import logging
from pathlib import Path
import shutil
import tempfile

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure temp directory using system's temp directory
TEMP_DIR = Path(tempfile.gettempdir()) / "ffmpeg_api"

def check_disk_space():
    """Check if disk space is available"""
    try:
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_gb = free // (1024 * 1024 * 1024)  # Convert to GB
        logger.info(f"Available disk space: {free_gb}GB")
        
        if free < used:  # Simple check: at least as much free space as the space being used
            raise RuntimeError(f"Insufficient disk space. Only {free_gb}GB available")
            
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        # Don't block processing, just log the error
        pass

def create_app():
    """Application factory function"""
    app = Flask(__name__)

    # Initialize temp directory
    try:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(exist_ok=True)
        logger.info(f"Initialized temporary directory: {TEMP_DIR}")
    except Exception as e:
        logger.error(f"Error initializing temp directory: {e}")

    def cleanup_files(*files):
        """Clean up temporary files"""
        for file in files:
            try:
                if file and os.path.exists(file):
                    os.remove(file)
                    logger.debug(f"Cleaned up temp file: {file}")
            except Exception as e:
                logger.error(f"Error cleaning up {file}: {e}")

    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy", 
            "service": "ffmpeg-api",
            "mode": "development" if app.debug else "production"
        }), 200

    @app.route('/captionize', methods=['POST'])
    def captionize_video():
        """Add ASS subtitles to video using FFmpeg"""
        logger.info("Received captionize request")
        
        # Check available disk space
        check_disk_space()
        
        # Initialize paths as None for cleanup
        video_path = None
        ass_path = None
        output_path = None
        
        try:
            # Validate request files
            if 'input_video_file' not in request.files or 'input_ass_file' not in request.files:
                logger.warning("Missing required files in request")
                return jsonify({
                    "error": "Both video and ASS subtitle files are required",
                    "details": "Use 'input_video_file' for video and 'input_ass_file' for ASS subtitle file. Note: Only .ass subtitle files are supported."
                }), 400

            video_file = request.files['input_video_file']
            ass_file = request.files['input_ass_file']
            custom_command = request.form.get('custom_command', '')

            # Validate file names and types
            if video_file.filename == '':
                return jsonify({"error": "No video file selected"}), 400
            if ass_file.filename == '':
                return jsonify({"error": "No ASS subtitle file selected"}), 400

            # Validate ASS file extension
            if not ass_file.filename.lower().endswith('.ass'):
                return jsonify({
                    "error": "Invalid subtitle file format",
                    "details": "Only .ass subtitle files are supported. Other formats like .srt, .vtt, etc. are not supported."
                }), 400

            # Generate temporary file paths
            temp_id = str(uuid.uuid4())
            video_path = TEMP_DIR / f"video_{temp_id}{Path(video_file.filename).suffix}"
            ass_path = TEMP_DIR / f"sub_{temp_id}.ass"  # Force .ass extension
            output_path = TEMP_DIR / f"output_{temp_id}{Path(video_file.filename).suffix}"

            # Save uploaded files
            logger.info(f"Saving temporary files: {video_path.name}, {ass_path.name}")
            video_file.save(str(video_path))
            ass_file.save(str(ass_path))

            # Change to temp directory to use relative paths
            original_cwd = os.getcwd()
            os.chdir(TEMP_DIR)
            
            try:
                # Use relative paths for FFmpeg
                relative_video = Path(video_path).name
                relative_ass = Path(ass_path).name
                relative_output = Path(output_path).name

                # Construct FFmpeg command with relative paths
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-i', relative_video,
                    '-vf', f'ass={relative_ass}',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-crf', '22',
                    '-c:a', 'copy',
                    relative_output
                ]

                # Apply custom FFmpeg parameters if provided
                if custom_command:
                    logger.info(f"Applying custom FFmpeg parameters: {custom_command}")
                    custom_params = custom_command.split()
                    # Insert custom parameters before output file
                    ffmpeg_cmd[-1:] = custom_params + [ffmpeg_cmd[-1]]

                logger.info(f"Executing FFmpeg command: {' '.join(ffmpeg_cmd)}")
                
                # Execute FFmpeg
                result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    text=True
                )

                if result.returncode != 0:
                    logger.error(f"FFmpeg error: {result.stderr}")
                    return jsonify({"error": "FFmpeg processing failed", "details": result.stderr}), 500

                logger.info("Video processing completed successfully")
                return send_file(
                    str(output_path),
                    as_attachment=True,
                    download_name=output_path.name
                )

            finally:
                # Change back to original directory
                os.chdir(original_cwd)

        except Exception as e:
            logger.exception("Unexpected error during video processing")
            return jsonify({"error": str(e)}), 500

        finally:
            cleanup_files(video_path, ass_path, output_path)

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Global exception handler"""
        logger.exception("Unhandled exception occurred")
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500

    return app

# Create the application instance
# This is used by both Flask development server and Gunicorn
app = create_app()

def main():
    """Entry point for local development server"""
    logger.info("Starting development server...")
    logger.info("Note: For production, use Gunicorn via Docker instead")
    app.run(host='0.0.0.0', port=8000, debug=True)

if __name__ == '__main__':
    main()