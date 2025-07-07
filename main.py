import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select
from datetime import datetime, timedelta
import sqlite3
import os
from flask import Flask
from threading import Thread

# --- Código para manter o bot ativo no Replit ---
app = Flask('')
@app.route('/')
def home():
    return 'Bot online'

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()
# -----------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Configurações de diretórios de upload simulando Google Drive
DRIVE_BASE = "./uploads"
os.makedirs(DRIVE_BASE, exist_ok=True)

# Conexão com o banco de dados
conn = sqlite3.connect('escrituras.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS escrituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT,
    nome TEXT,
    tipo TEXT,
    status TEXT,
    responsavel TEXT,
    criado_em TEXT,
    atualizado_em TEXT
)''')
c.execute('''CREATE TABLE IF NOT EXISTS checklists (
    codigo TEXT,
    documento TEXT,
    entregue INTEGER DEFAULT 0
)''')
conn.commit()

# Geração de código único
def gerar_codigo():
    ano = datetime.now().year
    c.execute("SELECT COUNT(*) FROM escrituras")
    count = c.fetchone()[0] + 1
    return f"ESC{ano}-{count:04d}"

# Checklist base por tipo de escritura
CHECKLIST_POR_TIPO = {
    "Doação": ["RG/CPF das partes", "Certidão do imóvel", "Certidão de casamento", "Comprovante de endereço"],
    "Compra e Venda": ["RG/CPF comprador/vendedor", "Matrícula atualizada", "Contrato de compra e venda", "Comprovante de pagamento"]
}

# Criar nova escritura
@bot.command()
async def criar(ctx, nome: str, tipo: str):
    codigo = gerar_codigo()
    agora = datetime.now().isoformat()
    c.execute("INSERT INTO escrituras (codigo, nome, tipo, status, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?)",
              (codigo, nome, tipo, "📥 Recebida", agora, agora))
    documentos = CHECKLIST_POR_TIPO.get(tipo, [])
    for doc in documentos:
        c.execute("INSERT INTO checklists (codigo, documento) VALUES (?, ?)", (codigo, doc))
    conn.commit()

    os.makedirs(f"{DRIVE_BASE}/{codigo}", exist_ok=True)

    embed = discord.Embed(title=f"📝 Nova Escritura Criada", color=0x3498db)
    embed.add_field(name="Código", value=codigo, inline=False)
    embed.add_field(name="Nome do Cliente", value=nome, inline=True)
    embed.add_field(name="Tipo", value=tipo, inline=True)
    embed.add_field(name="Status", value="📥 Recebida", inline=False)
    embed.set_footer(text=f"Criado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    view = View()
    view.add_item(Button(label="✏️ Assumir", style=discord.ButtonStyle.primary, custom_id=f"assumir_{codigo}"))
    view.add_item(Button(label="📋 Checklist", style=discord.ButtonStyle.secondary, custom_id=f"checklist_{codigo}"))
    view.add_item(Button(label="✅ Marcar Doc", style=discord.ButtonStyle.success, custom_id=f"marcar_{codigo}"))
    view.add_item(Button(label="📎 Upload", style=discord.ButtonStyle.success, custom_id=f"upload_{codigo}"))
    view.add_item(Button(label="📊 Painel Geral", style=discord.ButtonStyle.secondary, custom_id="painel_geral"))

    await ctx.send(embed=embed, view=view)

# Comando para alterar status
@bot.command()
async def status(ctx, codigo: str, novo_status: str):
    agora = datetime.now().isoformat()
    c.execute("UPDATE escrituras SET status = ?, atualizado_em = ? WHERE codigo = ?", (novo_status, agora, codigo))
    conn.commit()
    await ctx.send(f"✅ Status da escritura `{codigo}` atualizado para `{novo_status}`")

# Evento de interação
@bot.event
async def on_interaction(interaction):
    custom_id = interaction.data.get("custom_id")
    if custom_id.startswith("assumir_"):
        codigo = custom_id.split("_")[1]
        c.execute("UPDATE escrituras SET responsavel = ?, atualizado_em = ? WHERE codigo = ?",
                  (interaction.user.name, datetime.now().isoformat(), codigo))
        conn.commit()
        await interaction.response.send_message(f"✏️ Você assumiu a escritura `{codigo}`.", ephemeral=True)

    elif custom_id.startswith("checklist_"):
        codigo = custom_id.split("_")[1]
        c.execute("SELECT documento, entregue FROM checklists WHERE codigo = ?", (codigo,))
        docs = c.fetchall()
        checklist = "\n".join([f"{'✅' if ent else '❌'} {doc}" for doc, ent in docs])
        await interaction.response.send_message(embed=discord.Embed(title=f"📋 Checklist {codigo}", description=checklist), ephemeral=True)

    elif custom_id.startswith("marcar_"):
        codigo = custom_id.split("_")[1]
        c.execute("SELECT documento FROM checklists WHERE codigo = ? AND entregue = 0", (codigo,))
        pendentes = c.fetchall()
        if not pendentes:
            await interaction.response.send_message("✅ Todos os documentos já foram entregues!", ephemeral=True)
            return
        options = [discord.SelectOption(label=doc[0], value=doc[0]) for doc in pendentes[:25]]
        class MarcarSelect(Select):
            def __init__(self):
                super().__init__(placeholder="Documento entregue...", options=options)
            async def callback(self, i):
                c.execute("UPDATE checklists SET entregue = 1 WHERE codigo = ? AND documento = ?", (codigo, self.values[0]))
                conn.commit()
                await i.response.send_message(f"✅ Documento `{self.values[0]}` marcado como entregue.", ephemeral=True)
        view = View()
        view.add_item(MarcarSelect())
        await interaction.response.send_message("📋 Selecione o documento entregue:", view=view, ephemeral=True)

    elif custom_id.startswith("upload_"):
        await interaction.response.send_message("📎 Envie o arquivo neste canal com o código da escritura no comentário da mensagem.", ephemeral=True)

    elif custom_id == "painel_geral":
        c.execute("SELECT codigo, nome, tipo, status, responsavel FROM escrituras")
        escrituras = c.fetchall()
        embed = discord.Embed(title="📊 Painel Geral de Escrituras", color=0x8e44ad)
        for cod, nome, tipo, status, resp in escrituras:
            embed.add_field(name=f"{cod} - {tipo}", value=f"👤 {resp or 'N/A'}\n📌 {status}\n🏷️ {nome}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Receber arquivos enviados
@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.attachments:
        for anexo in message.attachments:
            for word in message.content.split():
                if word.startswith("ESC"):
                    pasta = f"{DRIVE_BASE}/{word}"
                    if os.path.exists(pasta):
                        path = os.path.join(pasta, anexo.filename)
                        await anexo.save(path)
                        await message.channel.send(f"📁 Documento `{anexo.filename}` salvo em `{word}`.")
                        return
                    else:
                        await message.channel.send("❌ Código de escritura inválido ou inexistente.")
                        return

bot.run(os.getenv('DISCORD_TOKEN'))
