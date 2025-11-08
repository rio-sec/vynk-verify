import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

class VYNKBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=os.getenv('APPLICATION_ID')
        )
    
    async def setup_hook(self):
        print("🔄 Starting command setup...")
        
        # Start the working bot API server
        try:
            from working_bot_api import start_working_api
            start_working_api(self)
            print("✅ Working Bot API server started on port 5001")
        except Exception as e:
            print(f"❌ Error starting bot API: {e}")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            print(f"✅ Successfully synced {len(synced)} global command(s)!")
            
            for cmd in synced:
                print(f"   - /{cmd.name}")
            
        except Exception as e:
            print(f"❌ Error during global sync: {e}")
    
    async def send_log(self, guild_id: str, title: str, description: str, color: int = 0x3B82F6):
        """Send a log message to the guild's configured log channel"""
        try:
            # Get log channel from database
            from database import db
            cursor = db.conn.cursor()
            cursor.execute('SELECT log_channel FROM server_settings WHERE guild_id = ?', (guild_id,))
            result = cursor.fetchone()
            
            if not result or not result[0]:
                print(f"ℹ️ No log channel configured for guild {guild_id}")
                return
            
            log_channel_id = int(result[0])
            channel = self.get_channel(log_channel_id)
            
            if channel:
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=color,
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="VYNK Verification System")
                await channel.send(embed=embed)
                print(f"📝 Log sent to channel {log_channel_id} in guild {guild_id}")
            else:
                print(f"⚠️ Could not find log channel {log_channel_id} in guild {guild_id}")
        
        except Exception as e:
            print(f"❌ Error sending log: {e}")

    async def send_verification_log(self, guild_id: str, user: discord.Member, method: str, status: str):
        """Send a verification log message"""
        if status == "success":
            title = "✅ Verification Success"
            description = f"**User:** {user.mention}\n**Method:** {method}\n**ID:** {user.id}"
            color = 0x10B981  # Green
        else:
            title = "❌ Verification Failed"
            description = f"**User:** {user.mention}\n**Method:** {method}\n**ID:** {user.id}"
            color = 0xEF4444  # Red
        
        await self.send_log(guild_id, title, description, color)

    async def on_ready(self):
        print(f'✅ {self.user} has logged in successfully!')
        print(f'📊 Connected to {len(self.guilds)} servers')
        
        try:
            commands_list = await self.tree.fetch_commands()
            print(f"🔄 Available global commands: {[cmd.name for cmd in commands_list]}")
        except Exception as e:
            print(f"❌ Error checking commands: {e}")
        
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="verification system"))

# Initialize bot
bot = VYNKBot()

# Web Verification View
class WebVerificationView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    
    @discord.ui.button(label="Verify on Web", style=discord.ButtonStyle.primary, emoji="🌐", custom_id="web_verify_button")
    async def web_verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create web verification URL (uses VYNK_BASE_URL env var if set)
        web_url = f"{os.getenv('VYNK_BASE_URL', 'http://localhost:5000')}/verify/{interaction.guild.id}/{interaction.user.id}"
        
        embed = discord.Embed(
            title="🌐 Web Verification",
            description="Click the link below to complete verification on our secure portal:",
            color=0x3B82F6
        )
        embed.add_field(
            name="Verification Link",
            value=f"[Click here to verify]({web_url})",
            inline=False
        )
        embed.add_field(
            name="What to expect:",
            value="• Security check with geolocation\n• Multiple verification methods\n• Instant role assignment",
            inline=False
        )
        embed.set_footer(text="This link is unique to you and will expire after use")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Button Verification View
class VerificationView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    
    @discord.ui.button(label="Verify", style=discord.ButtonStyle.primary, emoji="✅", custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Get server settings from database
            from database import db
            cursor = db.conn.cursor()
            cursor.execute('SELECT verified_role, log_channel FROM server_settings WHERE guild_id = ?', (str(interaction.guild.id),))
            result = cursor.fetchone()
            
            if not result:
                embed = discord.Embed(
                    title="❌ Configuration Error",
                    description="This server hasn't been set up properly. Please contact an administrator.",
                    color=0xEF4444
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            verified_role_id = result[0]
            verified_role = interaction.guild.get_role(int(verified_role_id))
            
            if verified_role:
                # Check if user already has the role
                if verified_role in interaction.user.roles:
                    embed = discord.Embed(
                        title="✅ Already Verified",
                        description="You are already verified!",
                        color=0x10B981
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Add the role
                await interaction.user.add_roles(verified_role)
                
                # Log verification to database
                db.log_verification(
                    guild_id=str(interaction.guild.id),
                    user_id=str(interaction.user.id),
                    user_name=str(interaction.user),
                    method="button",
                    status="success"
                )
                
                # Send log to log channel
                await interaction.client.send_verification_log(
                    guild_id=str(interaction.guild.id),
                    user=interaction.user,
                    method="button",
                    status="success"
                )
                
                # Success message
                embed = discord.Embed(
                    title="🎉 Verification Complete!",
                    description="Welcome to the server! You now have access to all channels.",
                    color=0x10B981
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            else:
                raise Exception("Verified role not found")
                
        except Exception as e:
            print(f"Verification error: {e}")
            # Log failed verification
            from database import db
            db.log_verification(
                guild_id=str(interaction.guild.id),
                user_id=str(interaction.user.id),
                user_name=str(interaction.user),
                method="button",
                status="failed"
            )
            
            # Send failure log
            await interaction.client.send_verification_log(
                guild_id=str(interaction.guild.id),
                user=interaction.user,
                method="button", 
                status="failed"
            )
            
            embed = discord.Embed(
                title="❌ Verification Failed",
                description="Could not verify you. Please contact an administrator.",
                color=0xEF4444
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

# ========== SLASH COMMANDS ==========

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Bot latency: {latency}ms",
        color=0x10B981
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="test", description="Test if bot is working")
async def test(interaction: discord.Interaction):
    embed = discord.Embed(
        title="VYNK Test",
        description="✅ Bot is working correctly!",
        color=0x3B82F6
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sync", description="Sync slash commands (Admin only)")
async def sync(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        synced = await bot.tree.sync()
        await interaction.response.send_message(f"✅ Synced {len(synced)} commands globally!", ephemeral=True)
        print(f"🔧 Manual sync completed: {len(synced)} commands")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error syncing commands: {e}", ephemeral=True)

@bot.tree.command(name="setup-verification", description="Setup button verification system")
@app_commands.describe(
    channel="Channel for verification",
    verified_role="Role to give after verification",
    log_channel="Channel for logs (optional)"
)
async def setup_verification(interaction: discord.Interaction, 
                           channel: discord.TextChannel, 
                           verified_role: discord.Role,
                           log_channel: discord.TextChannel = None):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need administrator permissions.", ephemeral=True)
        return
    
    # Save settings to database
    from database import db
    db.save_server_settings(
        guild_id=str(interaction.guild.id),
        verification_channel=str(channel.id),
        verified_role=str(verified_role.id),
        log_channel=str(log_channel.id) if log_channel else None,
        method='button'
    )
    
    # Create verification embed
    embed = discord.Embed(
        title="🔐 Button Verification",
        description="Click the button below to verify yourself and access the server!",
        color=0x3B82F6
    )
    embed.add_field(
        name="How it works",
        value="1. Click the Verify button\n2. Get verified role instantly\n3. Access all channels",
        inline=False
    )
    
    view = VerificationView(str(interaction.guild.id))
    await channel.send(embed=embed, view=view)
    
    # Confirm setup
    success_embed = discord.Embed(
        title="✅ Button Verification Setup Complete!",
        description=f"**Verification System Activated**\n\n📋 Verification Channel: {channel.mention}\n🎯 Verified Role: {verified_role.mention}\n📊 Logs: {log_channel.mention if log_channel else 'Not set'}",
        color=0x10B981
    )
    await interaction.response.send_message(embed=success_embed, ephemeral=True)

@bot.tree.command(name="setup-captcha", description="Setup CAPTCHA verification system")
@app_commands.describe(
    channel="Channel for CAPTCHA verification",
    verified_role="Role to give after verification",
    log_channel="Channel for logs (optional)"
)
async def setup_captcha(interaction: discord.Interaction, 
                       channel: discord.TextChannel, 
                       verified_role: discord.Role,
                       log_channel: discord.TextChannel = None):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need administrator permissions.", ephemeral=True)
        return
    
    # Save settings to database
    from database import db
    db.save_server_settings(
        guild_id=str(interaction.guild.id),
        verification_channel=str(channel.id),
        verified_role=str(verified_role.id),
        log_channel=str(log_channel.id) if log_channel else None,
        method='captcha'
    )
    
    embed = discord.Embed(
        title="🛡️ CAPTCHA Verification",
        description="CAPTCHA verification system has been set up!",
        color=0x3B82F6
    )
    embed.add_field(
        name="Configuration:",
        value=f"**Channel:** {channel.mention}\n**Role:** {verified_role.mention}\n**Logs:** {log_channel.mention if log_channel else 'Not set'}",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup-web-verification", description="Setup web-based verification system")
@app_commands.describe(
    channel="Channel for verification",
    verified_role="Role to give after verification", 
    log_channel="Channel for logs (optional)"
)
async def setup_web_verification(interaction: discord.Interaction, 
                               channel: discord.TextChannel, 
                               verified_role: discord.Role,
                               log_channel: discord.TextChannel = None):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need administrator permissions.", ephemeral=True)
        return
    
    # Save settings to database
    from database import db
    db.save_server_settings(
        guild_id=str(interaction.guild.id),
        verification_channel=str(channel.id),
        verified_role=str(verified_role.id),
        log_channel=str(log_channel.id) if log_channel else None,
        method='web'
    )
    
    # Create verification embed
    embed = discord.Embed(
        title="🌐 Web Verification System",
        description="Click the button below to start the verification process on our secure web portal.",
        color=0x3B82F6
    )
    embed.add_field(
        name="Features:",
        value="• Advanced security checks\n• Geolocation verification\n• Multiple verification methods\n• Real-time analytics",
        inline=False
    )
    
    # Send verification message
    view = WebVerificationView(str(interaction.guild.id))
    await channel.send(embed=embed, view=view)
    
    # Confirm setup
    success_embed = discord.Embed(
        title="✅ Web Verification Setup Complete!",
        description=f"**Web Verification System Activated**\n\n📋 Verification Channel: {channel.mention}\n🎯 Verified Role: {verified_role.mention}\n📊 Logs: {log_channel.mention if log_channel else 'Not set'}\n🌐 Portal: http://localhost:5000",
        color=0x10B981
    )
    await interaction.response.send_message(embed=success_embed, ephemeral=True)

@bot.tree.command(name="server-stats", description="Show server verification statistics")
async def server_stats(interaction: discord.Interaction):
    try:
        from database import db
        
        stats = db.get_server_stats(str(interaction.guild.id))
        
        embed = discord.Embed(
            title="📊 Server Verification Stats",
            description=f"Statistics for {interaction.guild.name}",
            color=0x3B82F6
        )
        
        embed.add_field(
            name="Total Verifications",
            value=f"`{stats['total_verifications']}`",
            inline=True
        )
        
        embed.add_field(
            name="Success Rate",
            value=f"`{stats['success_rate']}%`",
            inline=True
        )
        
        embed.add_field(
            name="Recent (24h)",
            value=f"`{stats['recent_verifications']}`",
            inline=True
        )
        
        embed.add_field(
            name="Successful",
            value=f"`{stats['success_verifications']}`",
            inline=True
        )
        
        embed.add_field(
            name="Failed",
            value=f"`{stats['failed_verifications']}`",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error",
            description="Could not fetch server statistics. Make sure verification is set up.",
            color=0xEF4444
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vynk-help", description="Show all VYNK commands")
async def vynk_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛠️ VYNK Commands",
        description="Here are all available commands:",
        color=0x3B82F6
    )
    
    embed.add_field(
        name="🔧 Setup Commands",
        value="• `/setup-verification` - Button verification\n• `/setup-captcha` - CAPTCHA verification\n• `/setup-web-verification` - Web portal verification\n• `/sync` - Sync commands (Admin)",
        inline=False
    )
    
    embed.add_field(
        name="📊 Utility Commands",
        value="• `/ping` - Check bot latency\n• `/test` - Test bot functionality\n• `/vynk-help` - This help menu\n• `/server-stats` - View verification stats",
        inline=False
    )
    
    embed.add_field(
        name="🌐 Web Dashboard",
        value="Visit `http://localhost:5000` for the web dashboard with analytics and verification portal.",
        inline=False
    )
    
    embed.set_footer(text="VYNK Premium Verification System")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_member_join(member):
    print(f"👤 {member} joined the server {member.guild.name}")
    
    # Find a channel named 'verification' or 'general'
    channel = discord.utils.get(member.guild.text_channels, name="verification")
    if not channel:
        channel = discord.utils.get(member.guild.text_channels, name="general")
    
    if channel:
        embed = discord.Embed(
            title=f"Welcome {member.name}! 👋",
            description="Please complete verification to access the server. Check the verification channel for instructions.",
            color=0x3B82F6
        )
        await channel.send(f"{member.mention}", embed=embed)

if __name__ == "__main__":
    print("🚀 Starting VYNK Bot...")
    print("🔧 Loading features:")
    print("   - Web Verification Portal")
    print("   - Button Verification System")
    print("   - CAPTCHA Verification System") 
    print("   - Bot API Server (Port 5001)")
    print("   - Abstract API Integration")
    print("   - Advanced Analytics")
    
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except discord.LoginFailure:
        print("❌ Invalid Discord token. Please check your .env file.")
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")