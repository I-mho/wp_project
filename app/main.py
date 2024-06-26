from fastapi import FastAPI, Request, Form, Depends, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
from uuid import uuid4

# 데이터베이스 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 데이터베이스 모델 정의
Base = declarative_base()

# 사용자 데이터베이스 정의
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    password = Column(String)
    session_id = Column(String)

# 게시글 데이터베이스 정의
class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    author = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# 게시글 댓글 데이터베이스 정의
class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer)
    author = Column(String)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# 데이터베이스 초기화
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# DB 세션 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_session(session_id: str = Cookie(None), db: Session = Depends(get_db)):
    if session_id:
        user = db.query(User).filter(User.session_id == session_id).first()
        return user if user else False
    else:
        return False

@app.get("/")
def base_page(req: Request, db: Session = Depends(get_db), session: User = Depends(check_session), page: int = 1):
    if session:
        page_size = 5
        total_posts = db.query(Post).count()
        total_pages = (total_posts + page_size - 1) // page_size
        posts = db.query(Post).order_by(Post.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return templates.TemplateResponse("base_s.html", {"request": req, "posts": posts, "user": session, "total_pages": total_pages, "current_page": page})
    else:
        return templates.TemplateResponse("base.html", {"request": req})

@app.get("/sign_up")
def sign_up_page(req: Request):
    return templates.TemplateResponse("signup.html", {"request": req})

@app.post("/sign_up/", response_class=HTMLResponse)
def sign_up(req: Request, name: str = Form(...), id: str = Form(...), pw: str = Form(...), db: Session = Depends(get_db)):
    existing_user_id = db.query(User).filter(User.id == id).first()
    existing_user_name = db.query(User).filter(User.name == name).first()

    id_error = "이미 존재하는 아이디입니다." if existing_user_id else ""
    name_error = "이미 존재하는 이름입니다." if existing_user_name else ""

    if id_error or name_error:
        return templates.TemplateResponse("signup.html", {
            "request": req,
            "id_error_msg": id_error,
            "name_error_msg": name_error,
            "id_error": bool(existing_user_id),
            "name_error": bool(existing_user_name)
        })

    session_id = str(uuid4())
    db_user = User(id=id, name=name, password=pw, session_id=session_id)
    db.add(db_user)
    db.commit()
    return RedirectResponse(url='/sign_up-success', status_code=303)

@app.get("/sign_up-success")
def success(req: Request):
    return templates.TemplateResponse("success.html", {"request": req})

@app.get("/sign_in")
def sign_in_page(req: Request):
    return templates.TemplateResponse("login.html", {"request": req})

@app.post("/sign_in/")
def sign_in(req: Request, id: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == id, User.password == password).first()
    if db_user:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="session_id", value=db_user.session_id)
        return response
    else:
        return templates.TemplateResponse("login.html", {"request": req, "error_msg": "아이디 또는 비밀번호가 틀렸습니다."})

@app.get("/logout")
def logout():
    res = RedirectResponse(url='/')
    res.delete_cookie("session_id")
    return res

@app.get("/mypage")
def mypage(req: Request, session: User = Depends(check_session)):
    if session:
        return templates.TemplateResponse("mypage.html", {"request": req, "user": session})
    else:
        return RedirectResponse(url='/sign_in')

@app.get("/myaccount")
def myaccount_page(req: Request, db: Session = Depends(get_db), session_id: str = Cookie(None)):
    db_user = db.query(User).filter(User.session_id == session_id).first()
    if db_user:
        return templates.TemplateResponse("myaccount.html", {"request": req, "user": db_user})
    else:
        return RedirectResponse(url="/sign_in", status_code=303)

@app.post("/myaccount/")
def update_account(req: Request, name: str = Form(...), password: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    if current_user:
        # 다른 사용자의 동일 이름 검사
        existing_name = db.query(User).filter(User.name == name, User.id != current_user.id).first()
        if existing_name:
            return templates.TemplateResponse("myaccount.html", {
                "request": req, 
                "user": current_user, 
                "error_msg": "이미 존재하는 이름입니다."
            })

        try:
            old_name = current_user.name
            current_user.name = name
            current_user.password = password

            db.query(Post).filter(Post.author == old_name).update({Post.author: name})
            db.query(Comment).filter(Comment.author == old_name).update({Comment.author: name})

            db.commit()
            return RedirectResponse(url='/', status_code=303)
        except Exception as e:
            db.rollback()
            return templates.TemplateResponse("myaccount.html", {
                "request": req, 
                "user": current_user, 
                "error_msg": "업데이트 실패: " + str(e)
            })
    return {"message": "업데이트 실패!"}


@app.get("/post/new")
def new_post_page(req: Request, session: User = Depends(check_session)):
    if session:
        return templates.TemplateResponse("newpost.html", {"request": req, "user": session})
    else:
        return RedirectResponse(url='/sign_in')

@app.post("/post/new")
def create_post(title: str = Form(...), content: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    if current_user:
        post = Post(title=title, content=content, author=current_user.name)
        db.add(post)
        db.commit()
        return RedirectResponse(url='/', status_code=303)
    else:
        return RedirectResponse(url='/sign_in')

@app.post("/post/{post_id}/comment")
def add_comment(post_id: int, content: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    if current_user:
        comment = Comment(post_id=post_id, author=current_user.name, content=content)
        db.add(comment)
        db.commit()
        return RedirectResponse(url=f'/post/{post_id}', status_code=303)
    else:
        return RedirectResponse(url='/sign_in')

@app.get("/post/{post_id}")
def read_post(post_id: int, req: Request, db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    post = db.query(Post).filter(Post.id == post_id).first()
    comments = db.query(Comment).filter(Comment.post_id == post_id).order_by(Comment.created_at).all()
    if post:
        return templates.TemplateResponse("post_detail.html", {"request": req, "post": post, "comments": comments, "user": current_user})
    else:
        return RedirectResponse(url='/')
    
# 게시글 수정 페이지
@app.get("/post/{post_id}/edit")
def edit_post_page(post_id: int, req: Request, db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if current_user and post and current_user.name == post.author:
        return templates.TemplateResponse("edit_post.html", {"request": req, "post": post})
    else:
        return RedirectResponse(url=f'/post/{post_id}', status_code=303)

# 게시글 수정 처리
@app.post("/post/{post_id}/edit")
def update_post(post_id: int, req: Request, title: str = Form(...), content: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if current_user and post and current_user.name == post.author:
        if len(title) > 20:
            return templates.TemplateResponse("edit_post.html", {"request": req, "post": post, "error": {"title": "제목은 20자 이하로 입력해주세요."}})
        post.title = title
        post.content = content
        db.commit()
        return RedirectResponse(url=f'/post/{post_id}', status_code=303)
    else:
        return RedirectResponse(url=f'/post/{post_id}', status_code=303)

# 게시글 삭제 처리
@app.post("/post/{post_id}/delete")
def delete_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if current_user and post and current_user.name == post.author:
        db.delete(post)
        db.commit()
    return RedirectResponse(url='/', status_code=303)
    
@app.post("/post/{post_id}/delete")
def delete_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(check_session)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if current_user and post.author == current_user.name:
        db.delete(post)
        db.commit()
        return RedirectResponse(url='/', status_code=303)
    else:
        return RedirectResponse(url='/')