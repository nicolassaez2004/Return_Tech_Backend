# Return Tech

Plataforma que conecta empresas a estudantes e profissionais de cibersegurança por meio de desafios técnicos e processos seletivos baseados em evidências práticas. O foco é permitir que as empresas identifiquem talentos pelo desempenho demonstrado em desafios realizados em ambientes autorizados.

## Estado atual

O Return Tech é um MVP funcional para desenvolvimento e testes. O frontend e o backend são executados localmente, enquanto o banco de dados é compartilhado pelo MongoDB Atlas.

Para disponibilizar o sistema publicamente, ainda será necessário hospedar o frontend e o backend, configurar HTTPS, restringir acessos e revisar as configurações de segurança para produção.

## Tecnologias

- **Frontend:** React + Vite.
- **Backend:** Python + Flask (API REST).
- **Banco de dados:** MongoDB Atlas.
- **Autenticação:** JWT.
- **Armazenamento de arquivos:** GridFS do MongoDB.

## Estrutura do projeto

A aplicação está organizada em duas pastas, que podem estar em repositórios separados:

```text
Return_Tech_Frontend/
Return_Tech_Backend/
```

## Requisitos

- Node.js.
- Python 3.11 ou superior.
- Git, caso o projeto seja obtido pelo GitHub.
- Conexão com a internet para acessar o MongoDB Atlas.

Utilize o Visual Studio Code ou outro editor de sua preferência. Os comandos deste guia consideram o PowerShell no Windows.

O Docker não é necessário para o fluxo principal com o Atlas. A alternativa com MongoDB local está descrita ao final deste guia.

## Configuração e execução local

### Backend

#### 1. Configurar o arquivo `.env`

O `.env` contém as configurações privadas do backend e não está no GitHub. Solicite o arquivo à pessoa responsável pelo projeto e coloque-o na pasta `Return_Tech_Backend`, no mesmo nível de `run.py`:

```text
Return_Tech_Backend/
├── .env
├── run.py
├── requirements.txt
└── app/
```

Estrutura de referência, com valores ilustrativos:

```env
MONGO_URI=mongodb+srv://USUARIO:SENHA@ENDERECO/return_tech?PARAMETROS
JWT_SECRET_KEY=CHAVE_SECRETA
FRONTEND_URL=http://localhost:5173
```

Para utilizar o Atlas compartilhado, use os valores do `.env` fornecido pela equipe, em vez dos exemplos acima.

- Confirme que `.env` está listado no `.gitignore` e nunca envie o arquivo ao GitHub.
- Não publique a `MONGO_URI`, pois ela contém as credenciais do banco.
- Ao pedir ajuda, não compartilhe capturas de tela ou mensagens que exponham senhas e outros segredos.

#### 2. Autorizar o acesso ao MongoDB Atlas

O endereço IP do computador precisa estar autorizado para acessar o banco compartilhado. Solicite à pessoa responsável pelo projeto que adicione seu IP atual em:

```text
MongoDB Atlas → Security → Network Access
```

As permissões de acesso ao painel do Atlas e as credenciais utilizadas pelo backend são controles diferentes.

#### 3. Preparar o ambiente Python

Abra um terminal PowerShell na pasta `Return_Tech_Backend`. Na primeira execução, crie e ative o ambiente virtual e instale as dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Quando o ambiente estiver ativo, o terminal exibirá `(.venv)` no início da linha. Reinstale as dependências sempre que o `requirements.txt` for alterado.

Se o PowerShell bloquear a ativação, consulte a seção de problemas comuns.

#### 4. Iniciar o backend

Com o ambiente virtual ativo, execute:

```powershell
python run.py
```

O backend estará disponível em <http://127.0.0.1:5000>. Para verificar a API, acesse <http://127.0.0.1:5000/api/health>.

Resposta esperada:

```json
{
  "service": "return-tech-api",
  "status": "ok"
}
```

### Frontend

Abra um segundo terminal PowerShell na pasta `Return_Tech_Frontend`. Na primeira execução, instale as dependências e inicie o frontend:

```powershell
npm install
npm run dev
```

Acesse <http://localhost:5173> no navegador.

O frontend utiliza `http://localhost:5000/api` como endereço padrão da API. Não é necessário criar um `.env` no frontend para executar o projeto localmente.

Mantenha os terminais do backend e do frontend abertos enquanto utilizar o sistema.

### Próximas execuções

Depois da configuração inicial, utilize um terminal para cada serviço.

**Terminal 1 — na pasta `Return_Tech_Backend`:**

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

**Terminal 2 — na pasta `Return_Tech_Frontend`:**

```powershell
npm run dev
```

Em seguida, acesse <http://localhost:5173>.

### Encerrar o sistema

Pressione `Ctrl + C` em cada terminal para encerrar o Flask e o React. Não é necessário desligar o MongoDB Atlas.

## Funcionamento do sistema

A interface possui fluxos para empresas, estudantes e profissionais, além de um painel reservado à administração da Return Tech.

As empresas definem competências, nível, modelo de trabalho, prazo e entregáveis dos desafios ou processos seletivos. Os participantes enviam soluções e evidências técnicas; a empresa avalia as entregas, registra pontuação e feedback e pode adicionar candidatos à lista de selecionados (*shortlist*).

A API é responsável por:

- autenticação com JWT;
- gerenciamento de usuários e perfis;
- criação, revisão e publicação de desafios;
- inscrições e envio de soluções;
- avaliações e feedbacks;
- portfólio de evidências;
- shortlist de candidatos;
- notificações;
- armazenamento de arquivos no GridFS do MongoDB.

### Como testar o fluxo completo

Antes de começar, tenha uma conta administrativa disponível, conforme as instruções da próxima seção.

1. Crie uma conta do tipo **Empresa** e cadastre as informações da empresa.
2. Crie um desafio de cibersegurança e envie-o para aprovação.
3. Entre com uma conta administrativa e aprove a publicação do desafio.
4. Abra uma janela anônima do navegador.
5. Crie uma conta do tipo **Estudante/Profissional** nessa janela.
6. Acesse o desafio aprovado e envie uma solução.
7. Volte à conta da empresa. Se tiver saído para acessar a administração, entre novamente.
8. Avalie a entrega e, se desejar, adicione o participante à shortlist.

A janela anônima permite manter as contas da empresa e do participante conectadas simultaneamente. Para a etapa administrativa, utilize outro perfil do navegador ou saia da conta atual e entre com a conta de administrador.

Esse teste utiliza o banco compartilhado no Atlas: contas, desafios, participações e avaliações ficam disponíveis para os integrantes autorizados.

## Administração dos desafios (CTFs)

O sistema possui três perfis:

| Perfil | Responsabilidades |
| --- | --- |
| `company` | Cadastrar e editar os próprios desafios e enviá-los para aprovação. |
| `talent` | Consultar desafios publicados, participar e enviar soluções. |
| `admin` | Administrar os desafios de todas as empresas. É reservado à equipe Return Tech. |

O cadastro público aceita apenas empresas e talentos.

### Criar uma conta administrativa

Crie uma conta administrativa exclusiva para cada integrante da equipe. No terminal da pasta `Return_Tech_Backend`, com o ambiente virtual ativo e a conexão ao MongoDB configurada, execute:

```powershell
python -m flask --app run.py create-admin
```

O comando solicita nome, e-mail, senha e confirmação da senha. A senha não é exibida durante a digitação, e apenas seu hash é armazenado. O comando cria uma nova conta; não promove contas existentes.

Depois, entre com essa conta em <http://localhost:5173/#/admin>. Quando o sistema estiver hospedado, utilize o endereço do frontend seguido de `/#/admin`.

### Painel administrativo

No painel, a equipe pode buscar e filtrar CTFs, consultar enunciados, editar campos, aprovar publicações, solicitar ajustes, encerrar desafios ou retirá-los da publicação, devolvendo-os ao estado de rascunho.

Cada desafio permanece associado à empresa que o criou. Os exemplos fictícios definidos no frontend não são registros do banco de dados.

### Fluxo de aprovação

| Transição | Responsável | Ação e requisitos |
| --- | --- | --- |
| `draft` → `pending_review` | Empresa responsável | Usar a ação `submit_review`. |
| `pending_review` → `published` | Administrador | Usar `approve`, com `review_revision` igual à revisão do enunciado exibida ao revisor. |
| `pending_review` → `changes_requested` | Administrador | Usar `request_changes`, com `review_revision` e uma justificativa em `feedback`. |

- A empresa pode editar e reenviar desafios que precisem de ajustes ou estejam encerrados. Alterações efetivas feitas pela empresa invalidam a aprovação e devolvem o desafio a `draft`.
- A ação antiga `publish`, quando utilizada por uma empresa, apenas solicita revisão. Para administradores, ela é um alias de `approve` e segue as mesmas validações.
- Apenas desafios em `published` ficam disponíveis para novos talentos. Desafios pendentes não permitem consulta direta, inscrição ou envio de soluções por talentos; a empresa responsável e a administração mantêm o acesso necessário à revisão.
- Participantes podem consultar desafios encerrados, mas não enviar novas soluções.
- A aprovação registra o administrador, a data e a revisão. Uma revisão desatualizada ou uma alteração concorrente resulta em HTTP `409`, exigindo atualizar e revisar o enunciado.
- A empresa recebe uma notificação quando o desafio é aprovado ou precisa de ajustes.
- O código não modifica retroativamente os registros que já estavam publicados.

### Rotas relacionadas à administração

| Método e rota | Comportamento |
| --- | --- |
| `GET /api/challenges/<id>` | Consultar detalhes. Rascunhos ficam restritos à empresa responsável e à administração. Participantes podem consultar desafios encerrados. |
| `PATCH /api/challenges/<id>` | Editar enunciado e metadados, pela empresa responsável ou por um administrador. |
| `GET /api/admin/challenges` | Listar todos os desafios. Acesso exclusivo de `admin`. |
| `PATCH /api/challenges/<id>/status` | Alterar o estado do desafio. Também aceita administradores; a ação `draft`, a aprovação e a solicitação de ajustes são exclusivas deles. |

## Testes automatizados

Na pasta `Return_Tech_Backend`, com o ambiente virtual ativo, execute:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Os testes utilizam um banco em memória, sem acessar o banco real. Eles verificam os estados, as permissões, a necessidade de nova aprovação após alterações e a proteção contra a publicação de conteúdo ainda não revisado.

## Problemas comuns

### O backend não inicia ou não conecta ao Atlas

Verifique se:

- o `.env` está na pasta `Return_Tech_Backend`;
- a `MONGO_URI` está completa e inclui o banco `return_tech`;
- o IP atual do computador está autorizado em **Network Access**;
- o computador está conectado à internet.

### Erro `NoneType object has no attribute users`

Esse erro pode indicar que o nome do banco está ausente na `MONGO_URI`. Verifique se o trecho após o endereço do cluster inclui `/return_tech`:

```text
Sem o nome do banco: .mongodb.net/?
Com o nome do banco: .mongodb.net/return_tech?
```

Não publique a conexão completa ao pedir ajuda.

### A página `http://127.0.0.1:5000` mostra 404

O backend não possui uma página visual na rota principal. Para verificar seu funcionamento, utilize <http://127.0.0.1:5000/api/health>.

### O site abre, mas cadastro e login não funcionam

Verifique se:

- o Flask está em execução na porta `5000`;
- o React está em execução na porta `5173`;
- <http://127.0.0.1:5000/api/health> retorna `"status": "ok"`;
- o navegador está acessando <http://localhost:5173>.

### O frontend não abre

Verifique se o terminal do frontend mostra:

```text
Local: http://localhost:5173/
```

Se as dependências ainda não tiverem sido instaladas, execute `npm install` na pasta `Return_Tech_Frontend` e inicie o serviço com `npm run dev`.

### O PowerShell não ativa a `.venv`

Na pasta `Return_Tech_Backend`, execute:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

A alteração da política de execução vale apenas para o terminal atual.

## Docker como alternativa opcional

O arquivo `docker-compose.yml` do backend permite testes com um MongoDB local. Essa alternativa exige o Docker instalado e não é necessária quando o projeto utiliza o Atlas.

Para usar o banco local, altere temporariamente a `MONGO_URI` no `.env`:

```env
MONGO_URI=mongodb://localhost:27017/return_tech
```

Na pasta `Return_Tech_Backend`, inicie o MongoDB:

```powershell
docker compose up -d
```

Os dados locais não são compartilhados com os outros integrantes. Ao voltar ao banco compartilhado, restaure a `MONGO_URI` do Atlas. Não é necessário executar o Docker nesse fluxo.
